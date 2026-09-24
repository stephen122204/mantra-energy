import copy
import sqlite3
import pytest
from studies.energy_diagnosis.moe.business_workload import create_tasks, verify
from studies.energy_diagnosis.moe.query_workload import QueryTool

QUERIES = [
    "SELECT segment,COUNT(*),SUM(cents) FROM transactions JOIN customers USING(customer_id) WHERE status='paid' AND year=2025 GROUP BY segment",
    "SELECT COUNT(*),COALESCE(SUM(cents),0) FROM transactions t LEFT JOIN customers c ON t.customer_id=c.customer_id WHERE status='paid' AND year=2025 AND c.customer_id IS NULL",
    "SELECT segment FROM transactions JOIN customers USING(customer_id) WHERE status='paid' GROUP BY segment HAVING SUM(CASE WHEN year=2024 THEN cents ELSE 0 END)>0 AND 5*SUM(CASE WHEN year=2025 THEN cents ELSE 0 END)<4*SUM(CASE WHEN year=2024 THEN cents ELSE 0 END) ORDER BY segment",
]

@pytest.mark.parametrize('rows,seed',[(32,0),(8192,7),(65536,29)])
def test_sql_answers_agree_with_independent_csv_reference(tmp_path,rows,seed):
    tasks=create_tasks(tmp_path/'assets',rows=rows,seed=seed)
    tool=QueryTool(str(tasks[0].asset_path/'business.sqlite'),tables=('customers','transactions'))
    assert set(tool.execute('schema')['tables'])=={'customers','transactions'}
    for index,task in enumerate(tasks):
        result=tool.execute('query',QUERIES[index]);data=result['rows']
        if index==0: answer={'by_segment':{s:{'count':n,'cents':v} for s,n,v in data}}
        elif index==1: answer={'count':data[0][0],'cents':data[0][1]}
        else:answer={'segments':[row[0] for row in data]}
        assert not result['truncated']
        assert verify(task,answer)['passed']
        wrong=copy.deepcopy(answer)
        if index==0: wrong['by_segment']['extra']={'count':0,'cents':0}
        elif index==1: wrong['count']+=1
        else: wrong['segments'].append('invented')
        assert not verify(task,wrong)['passed']
        assert task.expected=={}
        assert '-v2-' in task.task_id
        assert task.lineage == 'synthetic-business-v2'

@pytest.mark.parametrize('query',["DELETE FROM transactions","SELECT * FROM sqlite_master","ATTACH DATABASE ':memory:' AS other","PRAGMA table_info(transactions)"])
def test_tool_rejects_undeclared_reads_and_writes(tmp_path,query):
    task=create_tasks(tmp_path/'assets',rows=32)[0]
    tool=QueryTool(str(task.asset_path/'business.sqlite'),tables=('customers','transactions'))
    with pytest.raises(sqlite3.DatabaseError):tool.execute('query',query)

def test_preparation_reuses_inputs_and_refuses_corruption(tmp_path):
    tasks=create_tasks(tmp_path/'assets',rows=128)
    assert tasks==create_tasks(tmp_path/'assets',rows=128)
    path=tasks[0].asset_path/'transactions.csv';path.write_bytes(path.read_bytes()+b'corrupt')
    with pytest.raises(ValueError):create_tasks(tmp_path/'assets',rows=128)
    with pytest.raises(ValueError):verify(tasks[0],{})

def test_invalid_table_identifiers_rejected(tmp_path):
    with pytest.raises(ValueError):QueryTool(str(tmp_path/'none'),tables=('x);DROP TABLE x;',)).execute('schema')


# v2: v1 could return the same declines answer across seeds; each task holds every
# decline category, so the wrong queries below each change the answer.
WRONG = [
    (0, QUERIES[0].replace("status='paid' AND ","")),
    (0, QUERIES[0].replace("year=2025","year>=2025")),
    (0, QUERIES[0].replace(" AND year=2025", "")),
    (0, QUERIES[0].replace("COUNT(*)","COUNT(DISTINCT customer_id)")),
    (1, "SELECT COUNT(*),COALESCE(SUM(cents),0) FROM transactions WHERE status='paid' AND year=2025 AND customer_id NOT IN (SELECT customer_id FROM customers)"),
    (1, "SELECT COUNT(*),COALESCE(SUM(cents),0) FROM transactions WHERE status='paid' AND year=2025 AND customer_id IS NULL"),
    (1, QUERIES[1].replace("status='paid' AND ","")),
    (1, QUERIES[1]+" AND cents>0"),
    (2, QUERIES[2].replace(")<4*",")<=4*")),
    (2, QUERIES[2].replace("SUM(CASE WHEN year=2024 THEN cents ELSE 0 END)>0 AND ","")),
    (2, QUERIES[2].replace("WHERE status='paid' ","")),
]

def _answer(index,data):
    if index==0:return {'by_segment':{s:{'count':n,'cents':v} for s,n,v in data}}
    if index==1:return {'count':data[0][0],'cents':data[0][1]}
    return {'segments':[row[0] for row in data]}

@pytest.mark.parametrize('rows,seed',[(32,0),(512,3),(8192,19)])
@pytest.mark.parametrize('index,query',WRONG)
def test_wrong_queries_rejected(tmp_path,rows,seed,index,query):
    tasks=create_tasks(tmp_path/'assets',rows=rows,seed=seed)
    tool=QueryTool(str(tasks[0].asset_path/'business.sqlite'),tables=('customers','transactions'))
    assert not verify(tasks[index],_answer(index,tool.execute('query',query)['rows']))['passed']

def test_declines_follow_designed_categories_and_vary(tmp_path):
    import random
    from studies.energy_diagnosis.moe.business_workload import generate,reference,CATEGORIES,DECLINING,VERSION
    answers=set()
    for seed in range(12):
        tasks=create_tasks(tmp_path/f'a{seed}',rows=64,seed=seed)
        _,_,category=generate(64,random.Random(f'{VERSION}:{seed}'))
        assert set(category.values())==set(CATEGORIES)
        expected=sorted(s for s,k in category.items() if k in DECLINING)
        assert reference(tasks[2])=={'segments':expected}
        answers.add(tuple(expected))
        for constant in ([],sorted(category),sorted(category)[:1]):
            assert not verify(tasks[2],{'segments':constant})['passed']
    assert len(answers)>=6

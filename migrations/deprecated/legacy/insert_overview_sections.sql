-- =============================================================
-- insert_overview_sections.sql
-- Overview page layout matching playground exactly.
-- Run: sqlite3 data/experiments.db < scripts/migrations/insert_overview_sections.sql
--
-- Layout (matches playground):
--   Row 1: HeroStatBanner   — full width
--   Row 2: KPIStrip         — full width, 6 columns
--   Row 3: DataHealthBar    — full width, bare
--   Row 4: EnergyCompareCard | TaxMultiplierCard  — 2 cols
--   Row 5: PhaseBreakdownCard | EnergyTimelineCard — 2 cols
--   Row 6: SustainabilityRow — full width
--   Row 7: SessionListCard  — full width
--   Row 8: RunsTable        — full width
-- =============================================================

-- Clean overview sections
DELETE FROM page_sections WHERE page_id='overview';

-- Row 1: Hero — full width, bare (no card wrapper)
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',1,'HeroBanner','overview',NULL,'{}',1,1);

-- Row 2: KPI strip — 6 tiles
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',2,'KPIStrip','overview',NULL,'{"columns":6}',1,1);

-- Row 3: Data quality — full width, bare
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',3,'DataHealthBar','overview',NULL,'{}',1,1);

-- Row 4: Two-column row — Energy compare + Tax multiplier
-- Use a grid wrapper section (cols=2 tells PageRenderer to use 2-column grid)
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',4,'EnergyCompareCard','overview',NULL,'{}',2,1);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',5,'TaxMultiplierCard','tax_by_task',NULL,'{}',2,1);

-- Row 5: Two-column row — Phase breakdown + Energy timeline
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',6,'PhaseBreakdownCard','overview',NULL,'{}',2,1);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',7,'EnergyTimelineCard','overview',NULL,'{}',2,1);

-- Row 6: Sustainability — full width
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',8,'SustainabilityRow','overview','Sustainability Footprint','{}',1,1);

-- Row 7: Session list — full width
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',9,'SessionListCard','sessions','Recent Sessions','{"limit":5}',1,1);

-- Row 8: Runs table — full width
INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',10,'RunsTable','recent_runs','Recent Runs','{"limit":8}',1,1);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES ('overview',11,'LensExplorer','lens','🔬 Lens Explorer — Multi-Dimensional Research','{}',1,1);
-- Verify
-- SELECT position, component, cols, props FROM page_sections WHERE page_id='overview' ORDER BY position;

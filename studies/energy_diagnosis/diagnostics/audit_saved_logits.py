"""Independent CPU audit of preserved BF16 forward scores; no acceptance override."""
import hashlib

import torch



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(x, y):
    if x.shape != y.shape or x.ndim != 3 or x.shape[0] != 1 or x.shape[1] < 1 or x.shape[2] < 2:
        raise ValueError('expected matching nonempty [1, positions, vocabulary] scores')
    saved_dtype = str(x.dtype)
    x, y = x.double()[0], y.double()[0]
    if not torch.isfinite(x).all() or not torch.isfinite(y).all():
        raise ValueError('nonfinite scores')
    delta = y - x
    centered = delta - delta.mean(-1, keepdim=True)
    lx, ly = x.log_softmax(-1), y.log_softmax(-1)
    px, py = lx.exp(), ly.exp()
    tv = .5 * (px - py).abs().sum(-1)
    ax, ay = x.argmax(-1), y.argmax(-1)
    positions = []
    for i in range(len(x)):
        # Strict ranks avoid pretending an argmax tie is a strict preference.
        a, b = int(ax[i]), int(ay[i])
        positions.append(dict(
            position=i, input_final_position=i == len(x)-1,
            left_argmax=a, right_argmax=b, argmax_equal=a == b,
            left_top_tie_count=int((x[i] == x[i].max()).sum()),
            right_top_tie_count=int((y[i] == y[i].max()).sum()),
            left_winner_strict_rank_in_right=1 + int((y[i] > y[i,a]).sum()),
            right_winner_strict_rank_in_left=1 + int((x[i] > x[i,b]).sum()),
            left_margin=float(x[i].topk(2).values.diff().neg()[0]),
            right_margin=float(y[i].topk(2).values.diff().neg()[0]),
            total_variation=float(tv[i]),
            kl_left_to_right=float((px[i]*(lx[i]-ly[i])).sum()),
            left_top_probability=float(px[i,a]),
            right_top_probability=float(py[i,b]),
        ))
    return dict(
        shape=[1,*x.shape], dtype_saved=saved_dtype, analysis_dtype='float64',
        declared_atol=.02, declared_rtol=.01,
        original_script_allclose_left_right=bool(torch.allclose(x,y,atol=.02,rtol=.01)),
        reference_relative_tolerance_pass=bool(torch.allclose(y,x,atol=.02,rtol=.01)),
        fraction_outside_declared_reference_relative_tolerance=float((delta.abs() > .02+.01*x.abs()).double().mean()),
        rmse=float(delta.square().mean().sqrt()),
        centered_rmse=float(centered.square().mean().sqrt()),
        max_absolute_difference=float(delta.abs().max()),
        argmax_equal_positions=int((ax == ay).sum()), positions_count=len(x),
        final_position=positions[-1],
        differing_argmax_positions=[p for p in positions if not p['argmax_equal']],
        max_total_variation=float(tv.max()),
        mean_total_variation=float(tv.mean()),
    )


def self_checks():
    x = torch.tensor([[[2., 1., -1.], [1., 2., 0.]]])
    same = compare(x,x)
    assert same['rmse'] == 0 and same['max_total_variation'] == 0
    shift = compare(x,x+10)
    assert shift['rmse'] == 10 and shift['centered_rmse'] == 0
    assert shift['max_total_variation'] < 1e-14
    flip = compare(x,x.flip(-1))
    assert flip['argmax_equal_positions'] == 1 and flip['max_total_variation'] > 0
    tie = compare(torch.tensor([[[1.,1.,0.]]]), torch.tensor([[[0.,1.,1.]]]))
    assert tie['final_position']['left_top_tie_count'] == 2
    assert tie['final_position']['right_winner_strict_rank_in_left'] == 1

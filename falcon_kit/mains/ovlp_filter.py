


from builtins import range
from falcon_kit.multiproc import Pool
import falcon_kit.util.io as io
import argparse
import os
import sys

Reader = io.CapturedProcessReaderContext


def run_filter_stage1(db_fn, fn, la4falcon_flags, max_diff, max_ovlp, min_ovlp, min_len, min_idt):
    cmd = "LA4Falcon -%s %s %s" % (la4falcon_flags, db_fn, fn)
    reader = Reader(cmd)
    with reader:
        return fn, filter_stage1(reader.readlines, max_diff, max_ovlp, min_ovlp, min_len, min_idt)


def filter_stage1(readlines, max_diff, max_ovlp, min_ovlp, min_len, min_idt=90.0):
    def ignore(overlap_data):
        left_count = overlap_data["5p"]
        right_count = overlap_data["3p"]
        if (abs(left_count - right_count) > max_diff) or \
           (left_count > max_ovlp) or (right_count > max_ovlp) or \
           (left_count < min_ovlp) or (right_count < min_ovlp):
            return True

    ignore_rtn = set()    # reads to ignore downstream
    contained_rtn = set() # reads contained by a non-ignored read
    current_q_id = None
    overlap_data = {"5p": 0, "3p": 0}
    current_contained = set() # reads contained by current_q_id
    q_id = None
    for l in readlines():
        l = l.strip().split()
        q_id, t_id = l[:2]

        if q_id != current_q_id:
            if current_q_id is not None:
                if ignore(overlap_data):
                    ignore_rtn.add(current_q_id)
                else:
                    # q_id not ignored; so, record the reads it contains
                    contained_rtn.update(current_contained)
            overlap_data = {"5p": 0, "3p": 0}
            current_contained = set()
            current_q_id = q_id

        overlap_len = -int(l[2])
        idt = float(l[3])
        q_s, q_e, q_l = int(l[5]), int(l[6]), int(l[7])
        t_s, t_e, t_l = int(l[9]), int(l[10]), int(l[11])

        if idt < min_idt:
            continue
        if q_l < min_len or t_l < min_len:
            continue
        if q_s == 0:
            overlap_data["5p"] += 1
        if q_e == q_l:
            overlap_data["3p"] += 1
        if l[-1] == "contains":
            current_contained.add(t_id)
    if q_id is not None:
        if ignore(overlap_data):
            ignore_rtn.add(current_q_id)
        else:
            # q_id not ignored; so, record the reads it contains
            contained_rtn.update(current_contained)
    return { "ignore": ignore_rtn, "contained": contained_rtn }


def run_filter_stage2(db_fn, fn, la4falcon_flags, max_diff, max_ovlp, min_ovlp, min_len, min_idt, ignore_set, contained_set, bestn):
    cmd = "LA4Falcon -%s %s %s" % (la4falcon_flags, db_fn, fn)
    reader = Reader(cmd)
    with reader:
        return fn, filter_stage2(reader.readlines, max_diff, max_ovlp, min_ovlp, min_len, min_idt, ignore_set, contained_set, bestn)


def filter_stage2(readlines, max_diff, max_ovlp, min_ovlp, min_len, min_idt, ignore_set, contained_set, bestn):
    ovlp_output = []
    overlap_data = {"5p": [], "3p": []}
    current_q_id = None
    for l in readlines():
        l = l.strip().split()
        q_id, t_id = l[:2]

        if current_q_id == None:
            current_q_id = q_id
            overlap_data = {"5p": [], "3p": []}

        elif q_id != current_q_id:

            left = overlap_data["5p"]
            right = overlap_data["3p"]
            left.sort()
            right.sort()

            for i in range(len(left)):
                score, m_range, ovlp = left[i]
                ovlp_output.append(ovlp)
                # print " ".join(ovlp), read_end_data[current_q_id]
                if i >= bestn and m_range > 1000:
                    break

            for i in range(len(right)):
                score, m_range, ovlp = right[i]
                ovlp_output.append(ovlp)
                # print " ".join(ovlp), read_end_data[current_q_id]
                if i >= bestn and m_range > 1000:
                    break

            overlap_data = {"5p": [], "3p": []}
            current_q_id = q_id

        if q_id in contained_set:
            continue
        if t_id in contained_set:
            continue
        if q_id in ignore_set:
            continue
        if t_id in ignore_set:
            continue

        overlap_len = -int(l[2])
        idt = float(l[3])
        q_s, q_e, q_l = int(l[5]), int(l[6]), int(l[7])
        t_s, t_e, t_l = int(l[9]), int(l[10]), int(l[11])

        if idt < min_idt:
            continue
        if q_l < min_len or t_l < min_len:
            continue

        if q_s == 0:
            overlap_data["5p"].append((-overlap_len,  t_l - (t_e - t_s),  l))
        elif q_e == q_l:
            overlap_data["3p"].append((-overlap_len, t_l - (t_e - t_s), l))

    left = overlap_data["5p"]
    right = overlap_data["3p"]
    left.sort()
    right.sort()

    for i in range(len(left)):
        score, m_range, ovlp = left[i]
        ovlp_output.append(ovlp)
        # print " ".join(ovlp), read_end_data[current_q_id]
        if i >= bestn and m_range > 1000:
            break

    for i in range(len(right)):
        score, m_range, ovlp = right[i]
        ovlp_output.append(ovlp)
        # print " ".join(ovlp), read_end_data[current_q_id]
        if i >= bestn and m_range > 1000:
            break

    return ovlp_output


def run_ovlp_filter(outs, exe_pool, file_list, max_diff, max_cov, min_cov, min_len, min_idt, ignore_indels, bestn, db_fn):
    la4falcon_flags = "mo" + ("I" if ignore_indels else "")

    io.LOG('preparing filter_stage1')
    io.logstats()
    inputs = []
    for fn in file_list:
        if len(fn) != 0:
            inputs.append((run_filter_stage1, db_fn, fn, la4falcon_flags,
                           max_diff, max_cov, min_cov, min_len, min_idt))

    ignore_all = set()
    contained = set()
    for res in exe_pool.imap(io.run_func, inputs):
        ignore_all.update(res[1]["ignore"])
        contained.update(res[1]["contained"])
    contained = contained.difference(ignore_all) # do not count ignored reads as contained

    # print "all", len(contained)
    io.LOG('preparing filter_stage2')
    io.logstats()
    inputs = []
    for fn in file_list:
        if len(fn) != 0:
            inputs.append((run_filter_stage2, db_fn, fn, la4falcon_flags,
                           max_diff, max_cov, min_cov, min_len, min_idt, ignore_all, contained, bestn))
    for res in exe_pool.imap(io.run_func, inputs):
        for l in res[1]:
            outs.write(" ".join(l) + "\n")
    io.logstats()


def try_run_ovlp_filter(out_fn, n_core, fofn, max_diff, max_cov, min_cov, min_len, min_idt, ignore_indels, bestn, db_fn):
    io.LOG('starting ovlp_filter')
    file_list = io.validated_fns(fofn)
    io.LOG('fofn %r: %r' % (fofn, file_list))
    n_core = min(n_core, len(file_list))
    exe_pool = Pool(n_core)
    tmp_out_fn = out_fn + '.tmp'
    try:
        with open(tmp_out_fn, 'w') as outs:
            run_ovlp_filter(outs, exe_pool, file_list, max_diff, max_cov,
                            min_cov, min_len, min_idt, ignore_indels, bestn, db_fn)
            outs.write('---\n')
        os.rename(tmp_out_fn, out_fn)
        io.LOG('finished ovlp_filter')
    except:
        io.LOG('terminating ovlp_filter workers...')
        exe_pool.terminate()
        raise


def ovlp_filter(out_fn, n_core, las_fofn, max_diff, max_cov, min_cov, min_len, min_idt, ignore_indels, bestn, db_fn, debug, silent, stream):
    if debug:
        n_core = 0
        silent = False
    if silent:
        io.LOG = io.write_nothing
    if stream:
        global Reader
        Reader = io.StreamedProcessReaderContext
    try_run_ovlp_filter(out_fn, n_core, las_fofn, max_diff, max_cov,
                        min_cov, min_len, min_idt, ignore_indels, bestn, db_fn)


def parse_args(argv):
    epilog = """Output consists of selected lines from LA4Falcon -mo, e.g.
000000047 000000550 -206 100.000 0 0 206 603 1 0 206 741 overlap
"""

    class HelpF(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
        pass
    parser = argparse.ArgumentParser(
        description='a simple multi-processes LAS ovelap data filter',
        epilog=epilog,
        formatter_class=HelpF)
    parser.add_argument(
        '--out-fn', default='preads.ovl',
        help='Output filename')
    parser.add_argument(
        '--n-core', type=int, default=4,
        help='number of processes used for generating consensus; 0 for main process only')
    parser.add_argument(
        '--las-fofn', type=str,
        help='file contains the paths of all LAS files to be processed in parallel')
    parser.add_argument(
        '--db', type=str, dest='db_fn',
        help='read db file path')
    parser.add_argument(
        '--max-diff', type=int,
        help="max difference of 5' and 3' coverage")
    parser.add_argument(
        '--max-cov', type=int,
        help="max coverage of 5' or 3' end")
    parser.add_argument(
        '--min-cov', type=int,
        help="min coverage of 5' or 3' end")
    parser.add_argument(
        '--min-len', type=int, default=2500,
        help="min length of the reads")
    parser.add_argument(
        '--min-idt', type=float , default=90.0,
        help="minimum alignment identity to consider an overlap")
    parser.add_argument(
        '--ignore-indels', action='store_true',
        help="ignore indels in calculating alignment identity (-I to LA4Falcon)")
    parser.add_argument(
        '--bestn', type=int, default=10,
        help="output at least best n overlaps on 5' or 3' ends if possible")
    parser.add_argument(
        '--stream', action='store_true',
        help='stream from LA4Falcon, instead of slurping all at once; can save memory for large data')
    parser.add_argument(
        '--debug', '-g', action='store_true',
        help="single-threaded, plus other aids to debugging")
    parser.add_argument(
        '--silent', action='store_true',
        help="suppress cmd reporting on stderr")
    args = parser.parse_args(argv[1:])
    return args


def main(argv=sys.argv):
    args = parse_args(argv)
    ovlp_filter(**vars(args))


if __name__ == "__main__":
    main(sys.argv)

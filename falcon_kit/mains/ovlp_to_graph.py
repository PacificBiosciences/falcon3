import networkx as nx
import argparse
import logging
import os
import random
import re
import shlex
import subprocess
import sys

# Makes chimer_nodes stable; maybe others.
from ..util.ordered_set import OrderedSet as set

# Not sure if adds to stability, but at least adds determinism.
from collections import OrderedDict as dict

PYTHONHASHSEED = os.environ.get('PYTHONHASHSEED')
#random.seed(int(os.environ['PYTHONHASHSEED']))  # probably harmless but has no impact here
if PYTHONHASHSEED:
    import warnings
    warnings.warn('PYTHONHASHSEED={}'.format(PYTHONHASHSEED))

LOG = logging.getLogger(__name__)


class SGNode(object):
    """
    class representing a node in the string graph
    """

    def __init__(self, node_name):
        self.name = node_name
        self.out_edges = []
        self.in_edges = []

    def add_out_edge(self, out_edge):
        self.out_edges.append(out_edge)

    def add_in_edge(self, in_edge):
        self.in_edges.append(in_edge)


class SGEdge(object):
    """
    class representing an edge in the string graph
    """

    def __init__(self, in_node, out_node):
        self.in_node = in_node
        self.out_node = out_node
        self.attr = {}

    def set_attribute(self, attr, value):
        self.attr[attr] = value


def reverse_end(node_name):
    if (node_name == 'NA'):
        return node_name
    if (len(node_name) < 2 or (node_name[-2:] not in [':B', ':E'])):
        raise Exception(
            'Invalid node name. Node name passed to method: "{node_name}", expected format: "(%d)+:[BE]" or "NA".'.format(node_name=node_name))
    node_id, end = node_name.split(":")
    new_end = "B" if end == "E" else "E"
    return node_id + ":" + new_end


class StringGraph(object):
    """
    class representing the string graph
    """

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.e_reduce = {}
        self.best_in = {}

    def add_node(self, node_name):
        """
        add a node into the graph by given a node name
        """
        if node_name not in self.nodes:
            self.nodes[node_name] = SGNode(node_name)

    def add_edge(self, in_node_name, out_node_name, **attributes):
        """
        add an edge into the graph by given a pair of nodes
        """
        if (in_node_name, out_node_name) not in self.edges:

            self.add_node(in_node_name)
            self.add_node(out_node_name)
            in_node = self.nodes[in_node_name]
            out_node = self.nodes[out_node_name]

            edge = SGEdge(in_node, out_node)
            self.edges[(in_node_name, out_node_name)] = edge
            in_node.add_out_edge(edge)
            out_node.add_in_edge(edge)
        edge = self.edges[(in_node_name, out_node_name)]
        for (k, v) in attributes.items():
            edge.attr[k] = v

    def init_reduce_dict(self):
        for e in self.edges:
            self.e_reduce[e] = False

    def bfs_nodes(self, n, exclude=None, depth=5):
        all_nodes = set()
        all_nodes.add(n)
        candidate_nodes = set()
        candidate_nodes.add(n)
        dp = 1
        while dp < depth and len(candidate_nodes) > 0:
            v = candidate_nodes.pop()
            for e in v.out_edges:
                w = e.out_node
                if w == exclude:
                    continue
                if w not in all_nodes:
                    all_nodes.add(w)
                    if len(w.out_edges) > 0:
                        candidate_nodes.add(w)
            dp += 1

        return all_nodes

    def mark_chimer_edges(self):

        multi_in_nodes = {}
        multi_out_nodes = {}
        for n_name in self.nodes:
            n = self.nodes[n_name]
            out_nodes = [e.out_node for e in n.out_edges if self.e_reduce[(
                e.in_node.name, e.out_node.name)] == False]
            in_nodes = [e.in_node for e in n.in_edges if self.e_reduce[(
                e.in_node.name, e.out_node.name)] == False]

            if len(out_nodes) >= 2:
                multi_out_nodes[n_name] = out_nodes
            if len(in_nodes) >= 2:
                multi_in_nodes[n_name] = in_nodes

        chimer_candidates = set()
        out_set = set()
        in_set = set()
        for n_name in multi_out_nodes:
            out_nodes = set(multi_out_nodes[n_name])
            out_set |= out_nodes

        for n_name in multi_in_nodes:
            in_nodes = set(multi_in_nodes[n_name])
            in_set |= in_nodes

        chimer_candidates = out_set & in_set

        chimer_nodes = []
        chimer_edges = set()
        for n in chimer_candidates: # sort, or OrderedSet
            out_nodes = set([e.out_node for e in n.out_edges])
            test_set = set()
            for in_node in [e.in_node for e in n.in_edges]:
                test_set = test_set | set(
                    [e.out_node for e in in_node.out_edges])
            test_set -= set([n])
            if len(out_nodes & test_set) == 0:
                flow_node1 = set()
                flow_node2 = set()
                for v in list(out_nodes):
                    flow_node1 |= self.bfs_nodes(v, exclude=n)
                for v in list(test_set):
                    flow_node2 |= self.bfs_nodes(v, exclude=n)
                if len(flow_node1 & flow_node2) == 0:
                    for e in n.out_edges:
                        v, w = e.in_node.name, e.out_node.name
                        if self.e_reduce[(v, w)] != True:
                            self.e_reduce[(v, w)] = True
                            chimer_edges.add((v, w))
                            rv = reverse_end(w)
                            rw = reverse_end(v)
                            self.e_reduce[(rv, rw)] = True
                            chimer_edges.add((rv, rw))

                    for e in n.in_edges:
                        v, w = e.in_node.name, e.out_node.name
                        if self.e_reduce[(v, w)] != True:
                            self.e_reduce[(v, w)] = True
                            chimer_edges.add((v, w))
                            rv = reverse_end(w)
                            rw = reverse_end(v)
                            self.e_reduce[(rv, rw)] = True
                            chimer_edges.add((rv, rw))
                    chimer_nodes.append(n.name)
                    chimer_nodes.append(reverse_end(n.name))

        return chimer_nodes, chimer_edges

    def mark_spur_edge(self):

        removed_edges = set()
        for v in self.nodes:
            if len([e for e in self.nodes[v].out_edges if self.e_reduce[(e.in_node.name, e.out_node.name)] != True]) > 1:
                for out_edge in self.nodes[v].out_edges:
                    w = out_edge.out_node.name

                    if len(self.nodes[w].out_edges) == 0 and self.e_reduce[(v, w)] != True:
                        self.e_reduce[(v, w)] = True
                        removed_edges.add((v, w))
                        v2, w2 = reverse_end(w), reverse_end(v)
                        self.e_reduce[(v2, w2)] = True
                        removed_edges.add((v2, w2))

            if len([e for e in self.nodes[v].in_edges if self.e_reduce[(e.in_node.name, e.out_node.name)] != True]) > 1:
                for in_edge in self.nodes[v].in_edges:
                    w = in_edge.in_node.name
                    if len(self.nodes[w].in_edges) == 0 and self.e_reduce[(w, v)] != True:
                        self.e_reduce[(w, v)] = True
                        removed_edges.add((w, v))
                        v2, w2 = reverse_end(w), reverse_end(v)
                        self.e_reduce[(w2, v2)] = True
                        removed_edges.add((w2, v2))
        return removed_edges

    def mark_tr_edges(self):
        """
        transitive reduction
        """
        n_mark = {}
        e_reduce = self.e_reduce
        FUZZ = 500
        for n in self.nodes:
            n_mark[n] = "vacant"

        for (n_name, node) in self.nodes.items():

            out_edges = node.out_edges
            if len(out_edges) == 0:
                continue

            out_edges.sort(key=lambda x: x.attr["length"])

            for e in out_edges:
                w = e.out_node
                n_mark[w.name] = "inplay"

            max_len = out_edges[-1].attr["length"]

            max_len += FUZZ

            for e in out_edges:
                e_len = e.attr["length"]
                w = e.out_node
                if n_mark[w.name] == "inplay":
                    w.out_edges.sort(key=lambda x: x.attr["length"])
                    for e2 in w.out_edges:
                        if e2.attr["length"] + e_len < max_len:
                            x = e2.out_node
                            if n_mark[x.name] == "inplay":
                                n_mark[x.name] = "eliminated"

            for e in out_edges:
                e_len = e.attr["length"]
                w = e.out_node
                w.out_edges.sort(key=lambda x: x.attr["length"])
                if len(w.out_edges) > 0:
                    x = w.out_edges[0].out_node
                    if n_mark[x.name] == "inplay":
                        n_mark[x.name] = "eliminated"
                for e2 in w.out_edges:
                    if e2.attr["length"] < FUZZ:
                        x = e2.out_node
                        if n_mark[x.name] == "inplay":
                            n_mark[x.name] = "eliminated"

            for out_edge in out_edges:
                v = out_edge.in_node
                w = out_edge.out_node
                if n_mark[w.name] == "eliminated":
                    e_reduce[(v.name, w.name)] = True
                    v_name, w_name = reverse_end(w.name), reverse_end(v.name)
                    e_reduce[(v_name, w_name)] = True
                n_mark[w.name] = "vacant"

    def mark_best_overlap(self):
        """
        find the best overlapped edges
        """

        best_edges = set()
        removed_edges = set()

        for v in self.nodes:

            out_edges = self.nodes[v].out_edges
            if len(out_edges) > 0:
                out_edges.sort(key=lambda e: -e.attr["score"])
                for e in out_edges:
                    if self.e_reduce[(e.in_node.name, e.out_node.name)] != True:
                        best_edges.add((e.in_node.name, e.out_node.name))
                        break

            in_edges = self.nodes[v].in_edges
            if len(in_edges) > 0:
                in_edges.sort(key=lambda e: -e.attr["score"])
                for e in in_edges:
                    if self.e_reduce[(e.in_node.name, e.out_node.name)] != True:
                        best_edges.add((e.in_node.name, e.out_node.name))
                        self.best_in[v] = e.in_node.name
                        break

        LOG.debug(f"X {len(best_edges)}")

        for (e_n, e) in self.edges.items():
            v = e_n[0]
            w = e_n[1]
            if self.e_reduce[(v, w)] != True:
                if (v, w) not in best_edges:
                    self.e_reduce[(v, w)] = True
                    removed_edges.add((v, w))
                    v2, w2 = reverse_end(w), reverse_end(v)
                    self.e_reduce[(v2, w2)] = True
                    removed_edges.add((v2, w2))

        return removed_edges

    def resolve_repeat_edges(self):

        edges_to_reduce = []
        nodes_to_test = set()
        for (v_n, v) in self.nodes.items():

            out_nodes = []
            for e in v.out_edges:
                if self.e_reduce[(e.in_node.name, e.out_node.name)] == False:
                    out_nodes.append(e.out_node.name)

            in_nodes = []
            for e in v.in_edges:
                if self.e_reduce[(e.in_node.name, e.out_node.name)] == False:
                    in_nodes.append(e.in_node.name)

            if len(out_nodes) == 1 and len(in_nodes) == 1:
                nodes_to_test.add(v_n)

        for v_n in list(nodes_to_test):

            v = self.nodes[v_n]

            out_nodes = []
            for e in v.out_edges:
                if self.e_reduce[(e.in_node.name, e.out_node.name)] == False:
                    out_nodes.append(e.out_node.name)

            in_nodes = []
            for e in v.in_edges:
                if self.e_reduce[(e.in_node.name, e.out_node.name)] == False:
                    in_nodes.append(e.in_node.name)

            in_node_name = in_nodes[0]

            for out_edge in self.nodes[in_node_name].out_edges:
                vv = out_edge.in_node.name
                ww = out_edge.out_node.name

                ww_out = self.nodes[ww].out_edges
                v_out = self.nodes[v_n].out_edges
                ww_out_nodes = set([n.out_node.name for n in ww_out])
                v_out_nodes = set([n.out_node.name for n in v_out])
                o_overlap = len(ww_out_nodes & v_out_nodes)

                ww_in_count = 0
                for e in self.nodes[ww].in_edges:
                    if self.e_reduce[(e.in_node.name, e.out_node.name)] == False:
                        ww_in_count += 1

                if ww != v_n and\
                   self.e_reduce[(vv, ww)] == False and\
                   ww_in_count > 1 and\
                   ww not in nodes_to_test and\
                   o_overlap == 0:
                    edges_to_reduce.append((vv, ww))

            out_node_name = out_nodes[0]

            for in_edge in self.nodes[out_node_name].in_edges:
                vv = in_edge.in_node.name
                ww = in_edge.out_node.name

                vv_in = self.nodes[vv].in_edges
                v_in = self.nodes[v_n].in_edges
                vv_in_nodes = set([n.in_node.name for n in vv_in])
                v_in_nodes = set([n.in_node.name for n in v_in])
                i_overlap = len(vv_in_nodes & v_in_nodes)

                vv_out_count = 0
                for e in self.nodes[vv].out_edges:
                    if self.e_reduce[(e.in_node.name, e.out_node.name)] == False:
                        vv_out_count += 1

                if vv != v_n and\
                   self.e_reduce[(vv, ww)] == False and\
                   vv_out_count > 1 and\
                   vv not in nodes_to_test and\
                   i_overlap == 0:
                    edges_to_reduce.append((vv, ww))

        removed_edges = set()
        for e in edges_to_reduce:
            self.e_reduce[e] = True
            removed_edges.add(e)

        return removed_edges

def reverse_edge(e):
    e1, e2 = e
    return reverse_end(e2), reverse_end(e1)


def reverse_path(p):
    p = p[::-1]
    return [reverse_end(n) for n in p]


def find_bundle(ug, u_edge_data, start_node, depth_cutoff, width_cutoff, length_cutoff, no_out_edge_printed):

    tips = set()
    bundle_edges = set()
    bundle_nodes = set()

    local_graph = nx.ego_graph(ug, start_node, depth_cutoff, undirected=False)
    length_to_node = {start_node: 0}
    score_to_node = {start_node: 0}

    v = start_node
    end_node = start_node

    LOG.debug(f"\n\nstart {start_node}")

    bundle_nodes.add(v)
    for vv, ww, kk in local_graph.out_edges(v, keys=True):
        max_score = 0
        max_length = 0

        if (vv, ww, kk) not in bundle_edges and\
                reverse_end(ww) not in bundle_nodes:

            bundle_edges.add((vv, ww, kk))
            tips.add(ww)

    for v in list(tips):
        bundle_nodes.add(v)

    depth = 1
    width = 1.0
    converage = False

    while 1:
        LOG.debug(f"# of tips {len(tips)}")

        if len(tips) > 4:
            converage = False
            break

        if len(tips) == 1:
            end_node = tips.pop()

            LOG.debug(f"end {end_node}")

            if end_node not in length_to_node:
                v = end_node
                max_score_edge = None
                max_score = 0
                for uu, vv, kk in local_graph.in_edges(v, keys=True):
                    if uu not in length_to_node:
                        continue

                    score = u_edge_data[(uu, vv, kk)][1]

                    if score > max_score:

                        max_score = score
                        max_score_edge = (uu, vv, kk)

                length_to_node[v] = length_to_node[max_score_edge[0]
                                                   ] + u_edge_data[max_score_edge][0]
                score_to_node[v] = score_to_node[max_score_edge[0]
                                                 ] + u_edge_data[max_score_edge][1]

            converage = True
            break

        depth += 1
        width = 1.0 * len(bundle_edges) / depth

        if depth > 10 and width > width_cutoff:
            converage = False
            break

        if depth > depth_cutoff:
            converage = False
            break

        tips_list = list(tips)

        tip_updated = False
        loop_detect = False
        length_limit_reached = False

        for v in tips_list:
            LOG.debug(f"process {v}")

            if len(local_graph.out_edges(v, keys=True)) == 0:  # dead end route
                if v not in no_out_edge_printed:
                    print("no out edge", v)
                    no_out_edge_printed.add(v)
                continue

            max_score_edge = None
            max_score = 0

            extend_tip = True

            for uu, vv, kk in local_graph.in_edges(v, keys=True):
                LOG.debug(f"in_edges {uu} {vv} {kk}")
                LOG.debug(f"{uu} in length_to_node {uu in length_to_node}")

                if uu not in length_to_node:
                    extend_tip = False
                    break

                score = u_edge_data[(uu, vv, kk)][1]

                if score > max_score:

                    max_score = score
                    max_score_edge = (uu, vv, kk)

            if extend_tip:

                length_to_node[v] = length_to_node[max_score_edge[0]
                                                   ] + u_edge_data[max_score_edge][0]
                score_to_node[v] = score_to_node[max_score_edge[0]
                                                 ] + u_edge_data[max_score_edge][1]

                if length_to_node[v] > length_cutoff:
                    length_limit_reached = True
                    converage = False
                    break

                v_updated = False
                for vv, ww, kk in local_graph.out_edges(v, keys=True):

                    LOG.debug(f"test {vv} {ww} {kk}")

                    if ww in length_to_node:
                        loop_detect = True
                        LOG.debug(f"loop_detect {ww}")
                        break

                    if (vv, ww, kk) not in bundle_edges and\
                            reverse_end(ww) not in bundle_nodes:

                        LOG.debug(f"add {ww}")

                        tips.add(ww)
                        bundle_edges.add((vv, ww, kk))
                        tip_updated = True
                        v_updated = True

                if v_updated:

                    LOG.debug(f"remove {v}")

                    tips.remove(v)

                    if len(tips) == 1:
                        break

            if loop_detect:
                converage = False
                break

        if length_limit_reached:
            converage = False
            break

        if loop_detect:
            converage = False
            break

        if not tip_updated:
            converage = False
            break

        for v in list(tips):
            bundle_nodes.add(v)

    data = start_node, end_node, bundle_edges, length_to_node[
        end_node], score_to_node[end_node], depth

    data_r = None

    LOG.debug(f"{converage} {data} {data_r}")
    return converage, data, data_r

def init_string_graph(overlap_data):
    sg = StringGraph()

    overlap_set = set()
    for od in overlap_data:
        f_id, g_id, score, identity = od[:4]
        f_s, f_b, f_e, f_l = od[4:8]
        g_s, g_b, g_e, g_l = od[8:12]
        overlap_pair = [f_id, g_id]
        overlap_pair.sort()
        overlap_pair = tuple(overlap_pair)
        if overlap_pair in overlap_set:  # don't allow duplicated records
            continue
        else:
            overlap_set.add(overlap_pair)

        if g_s == 1:  # revered alignment, swapping the begin and end coordinates
            g_b, g_e = g_e, g_b

        # build the string graph edges for each overlap
        if f_b > 0:
            if g_b < g_e:
                """
                     f.B         f.E
                  f  ----------->
                  g         ------------->
                            g.B           g.E
                """
                if f_b == 0 or g_e - g_l == 0:
                    continue
                sg.add_edge("%s:B" % g_id, "%s:B" % f_id, label="%s:%d-%d"%(f_id, f_b, 0),
                            length=abs(f_b - 0),
                            score=-score,
                            identity=identity)
                sg.add_edge("%s:E" % f_id, "%s:E" % g_id, label="%s:%d-%d"%(g_id, g_e, g_l),
                            length=abs(g_e - g_l),
                            score=-score,
                            identity=identity)
            else:
                """
                     f.B         f.E
                  f  ----------->
                  g         <-------------
                            g.E           g.B
                """
                if f_b == 0 or g_e == 0:
                    continue
                sg.add_edge("%s:E" % g_id, "%s:B" % f_id, label="%s:%d-%d"%(f_id, f_b, 0),
                            length=abs(f_b - 0),
                            score=-score,
                            identity=identity)
                sg.add_edge("%s:E" % f_id, "%s:B" % g_id, label="%s:%d-%d"%(g_id, g_e, 0),
                            length=abs(g_e - 0),
                            score=-score,
                            identity=identity)
        else:
            if g_b < g_e:
                """
                                    f.B         f.E
                  f                 ----------->
                  g         ------------->
                            g.B           g.E
                """
                if g_b == 0 or f_e - f_l == 0:
                    continue
                sg.add_edge("%s:B" % f_id, "%s:B" % g_id, label="%s:%d-%d"%(g_id, g_b, 0),
                            length=abs(g_b - 0),
                            score=-score,
                            identity=identity)
                sg.add_edge("%s:E" % g_id, "%s:E" % f_id, label="%s:%d-%d"%(f_id, f_e, f_l),
                            length=abs(f_e - f_l),
                            score=-score,
                            identity=identity)
            else:
                """
                                    f.B         f.E
                  f                 ----------->
                  g         <-------------
                            g.E           g.B
                """
                if g_b - g_l == 0 or f_e - f_l == 0:
                    continue
                sg.add_edge("%s:B" % f_id, "%s:E" % g_id, label="%s:%d-%d"%(g_id, g_b, g_l),
                            length=abs(g_b - g_l),
                            score=-score,
                            identity=identity)
                sg.add_edge("%s:B" % g_id, "%s:E" % f_id, label="%s:%d-%d"%(f_id, f_e, f_l),
                            length=abs(f_e - f_l),
                            score=-score,
                            identity=identity)

    sg.init_reduce_dict()
    sg.mark_tr_edges()  # mark those edges that transitive redundant
    return sg

re_label = re.compile(r"(.*):(\d+)-(\d+)")

def init_digraph(sg, chimer_edges, removed_edges, spur_edges):
    nxsg = nx.DiGraph()
    edge_data = {}
    with open("sg_edges_list", "w") as out_f:
        for v, w in sg.edges: # sort, or OrderedDict
            e = sg.edges[(v, w)]
            label = e.attr["label"]
            score = e.attr["score"]
            identity = e.attr["identity"]
            length = e.attr["length"]
            try:
                mo = re_label.search(label)
                rid = mo.group(1)
                sp = int(mo.group(2))
                tp = int(mo.group(3))
            except Exception:
                msg = 'parsing label="{}"'.format(label)
                LOG.exception(msg)
                raise
            assert length == abs(sp - tp)

            if not sg.e_reduce[(v, w)]:
                type_ = "G"
            elif (v, w) in chimer_edges:
                type_ = "C"
            elif (v, w) in removed_edges:
                type_ = "R"
            elif (v, w) in spur_edges:
                type_ = "S"
            else:
                assert sg.e_reduce[(v, w)]
                type_ = "TR"

            if not sg.e_reduce[(v, w)]:
                assert label == "%s:%d-%d" % (rid, sp, tp)
                nxsg.add_edge(v, w, label=label, length=length, score=score)
                edge_data[(v, w)] = (rid, sp, tp, length, score, identity, type_)
                if w in sg.best_in:
                    nxsg.nodes[w]["best_in"] = v

            line = '%s %s %s %5d %5d %5d %5.2f %s' % (
                v, w, rid, sp, tp, score, identity, type_)
            print(line, file=out_f)

    return nxsg, edge_data


def yield_from_overlap_file(overlap_file):
    # loop through the overlapping data to load the data in the a python array

    with open(overlap_file) as f:
        for line in f:
            if line.startswith('-'):
                break
            l = line.strip().split()
            f_id, g_id, score, identity = l[:4]

            score = int(score)
            identity = float(identity)
            #contained_etc = l[12]
            f_strand, f_start, f_end, f_len = (int(c) for c in l[4:8])
            g_strand, g_start, g_end, g_len = (int(c) for c in l[8:12])

            yield (f_id, g_id, score, identity,
                                f_strand, f_start, f_end, f_len,
                                g_strand, g_start, g_end, g_len)

def generate_nx_string_graph(sg, lfc=False, disable_chimer_bridge_removal=False):
    LOG.debug("{}".format(sum([1 for c in sg.e_reduce.values() if c])))
    LOG.debug("{}".format(sum([1 for c in sg.e_reduce.values() if not c])))

    if not disable_chimer_bridge_removal:
        chimer_nodes, chimer_edges = sg.mark_chimer_edges()

        with open("chimers_nodes", "w") as f:
            for n in chimer_nodes:
                print(n, file=f)
        del chimer_nodes
    else:
        chimer_edges = set()  # empty set

    spur_edges = sg.mark_spur_edge()

    removed_edges = set()
    if lfc == True:
        removed_edges = sg.resolve_repeat_edges()
    else:
        # mark those edges that are best overlap edges
        removed_edges = sg.mark_best_overlap()

    spur_edges.update(sg.mark_spur_edge())

    LOG.debug('{}'.format(sum([1 for c in sg.e_reduce.values() if not c])))

    nxsg, edge_data = init_digraph(sg, chimer_edges, removed_edges, spur_edges)
    return nxsg, edge_data

def identify_branch_nodes(ug):

    branch_nodes = set()
    for n in ug.nodes():
        in_degree = len(ug.in_edges(n))
        out_degree = len(ug.out_edges(n))
        if in_degree > 1 or out_degree > 1:
            branch_nodes.add(n)

    return branch_nodes

def construct_compound_paths_0(ug, u_edge_data, branch_nodes):
    no_out_edge_printed = set()

    compound_paths_0 = []
    for p in list(branch_nodes):
        if ug.out_degree(p) > 1:
            coverage, data, data_r = find_bundle(
                ug, u_edge_data, p, 48, 16, 500000, no_out_edge_printed)
            if coverage == True:
                start_node, end_node, bundle_edges, length, score, depth = data
                compound_paths_0.append(
                    (start_node, "NA", end_node, 1.0 * len(bundle_edges) / depth, length, score, bundle_edges))

    compound_paths_0.sort(key=lambda x: -len(x[6]))
    return compound_paths_0

def construct_compound_paths_1(compound_paths_0):

    edge_to_cpath = {}
    compound_paths_1 = {}
    for s, v, t, width, length, score, bundle_edges in compound_paths_0:
        LOG.debug(f"constructing utg, test  {s} {v} {t}")

        overlapped = False
        for vv, ww, kk in list(bundle_edges):
            if (vv, ww, kk) in edge_to_cpath:
                LOG.debug(f"remove overlapped utg {(s, v, t)} {(vv, ww, kk)}")
                overlapped = True
                break
            rvv = reverse_end(vv)
            rww = reverse_end(ww)
            rkk = reverse_end(kk)
            if (rww, rvv, rkk) in edge_to_cpath:
                LOG.debug(f"remove overlapped r utg {(s, v, t)} {(rww, rvv, rkk)}")
                overlapped = True
                break

        if not overlapped:
            LOG.debug(f"constructing {s} {v} {t}")

            bundle_edges_r = []
            rs = reverse_end(t)
            rt = reverse_end(s)

            for vv, ww, kk in list(bundle_edges):
                edge_to_cpath.setdefault((vv, ww, kk), set())
                edge_to_cpath[(vv, ww, kk)].add((s, t, v))
                rvv = reverse_end(ww)
                rww = reverse_end(vv)
                rkk = reverse_end(kk)
                edge_to_cpath.setdefault((rvv, rww, rkk), set())
                edge_to_cpath[(rvv, rww, rkk)].add(
                    (rs, rt, v))  # assert v == "NA"
                bundle_edges_r.append((rvv, rww, rkk))

            compound_paths_1[(s, v, t)] = width, length, score, bundle_edges
            compound_paths_1[(rs, v, rt)
                             ] = width, length, score, bundle_edges_r
    return compound_paths_1

def construct_compound_paths_2(compound_paths_1):
    compound_paths_2 = {}
    edge_to_cpath = {}
    for s, v, t in compound_paths_1:
        rs = reverse_end(t)
        rt = reverse_end(s)
        if (rs, "NA", rt) not in compound_paths_1:
            LOG.debug(f"non_compliment bundle {s} {v} {t} {len(compound_paths_1[(s, v, t)][-1])}")
            continue
        width, length, score, bundle_edges = compound_paths_1[(s, v, t)]
        compound_paths_2[(s, v, t)] = width, length, score, bundle_edges
        for vv, ww, kk in list(bundle_edges):
            edge_to_cpath.setdefault((vv, ww, kk), set())
            edge_to_cpath[(vv, ww, kk)].add((s, t, v))
    return compound_paths_2, edge_to_cpath

def construct_compound_paths_3(ug, compound_paths_2, edge_to_cpath):
    compound_paths_3 = {}
    for (k, val) in compound_paths_2.items():

        start_node, NA, end_node = k
        rs = reverse_end(end_node)
        rt = reverse_end(start_node)
        assert (rs, "NA", rt) in compound_paths_2

        contained = False
        for vv, ww, kk in ug.out_edges(start_node, keys=True):
            if len(edge_to_cpath.get((vv, ww, kk), [])) > 1:
                contained = True

        if not contained:
            compound_paths_3[k] = val
            LOG.debug(f"compound {k}")
    return compound_paths_3

def construct_compound_paths(ug, u_edge_data):

    branch_nodes = identify_branch_nodes(ug)

    compound_paths_0 = construct_compound_paths_0(ug, u_edge_data, branch_nodes)
    compound_paths_1 = construct_compound_paths_1(compound_paths_0)
    compound_paths_2, edge_to_cpath = construct_compound_paths_2(compound_paths_1)
    compound_paths_3 = construct_compound_paths_3(ug, compound_paths_2, edge_to_cpath)

    compound_paths = {}
    for s, v, t in compound_paths_3:
        rs = reverse_end(t)
        rt = reverse_end(s)
        if (rs, "NA", rt) not in compound_paths_3:
            continue
        compound_paths[(s, v, t)] = compound_paths_3[(s, v, t)]

    return compound_paths

def identify_simple_paths(sg2, edge_data):
    # utg construction phase 1, identify all simple paths
    simple_paths = dict()
    s_nodes = set()
    t_nodes = set()
    simple_nodes = set()

    all_nodes = sg2.nodes()
    for n in all_nodes:
        in_degree = len(sg2.in_edges(n))
        out_degree = len(sg2.out_edges(n))
        if in_degree == 1 and out_degree == 1:
            simple_nodes.add(n)
        else:
            if out_degree != 0:
                s_nodes.add(n)
            if in_degree != 0:
                t_nodes.add(n)

    free_edges = set(sg2.edges())

    if LOG.getEffectiveLevel() >= logging.DEBUG:
        for s in list(simple_nodes):
            LOG.debug(f"simple_node {s}")
        for s in list(s_nodes):
            LOG.debug(f"s_node {s}")
        for s in list(t_nodes):
            LOG.debug(f"t_node {s}")

        for v, w in free_edges:
            if (reverse_end(w), reverse_end(v)) not in free_edges:
                LOG.debug(f"bug {v} {w}")
                print(reverse_end(w), reverse_end(v))

    while free_edges:
        if s_nodes:
            n = s_nodes.pop()
            LOG.debug(f"initial utg 1 {n}")
        else:
            e = free_edges.pop()
            free_edges.add(e)
            n = e[0]
            LOG.debug(f"initial utg 2 {n}")

        path = []
        path_length = 0
        path_score = 0
        for v, w in sg2.out_edges(n):
            if (v, w) not in free_edges:
                continue
            rv = reverse_end(v)
            rw = reverse_end(w)

            path_length = 0
            path_score = 0
            v0 = v
            w0 = w
            path = [v, w]
            path_edges = set()
            path_edges.add((v, w))
            path_length += edge_data[(v, w)][3]
            path_score += edge_data[(v, w)][4]
            free_edges.remove((v, w))

            r_path_length = 0
            r_path_score = 0
            rv0 = rv
            rw0 = rw
            r_path = [rv, rw]  # need to reverse again
            r_path_edges = set()
            r_path_edges.add((rw, rv))
            r_path_length += edge_data[(rw, rv)][3]
            r_path_score += edge_data[(rw, rv)][4]
            free_edges.remove((rw, rv))

            while w in simple_nodes:
                w, w_ = list(sg2.out_edges(w))[0]
                if (w, w_) not in free_edges:
                    break
                rw_, rw = reverse_end(w_), reverse_end(w)

                if (rw_, rw) in path_edges:
                    break

                path.append(w_)
                path_edges.add((w, w_))
                path_length += edge_data[(w, w_)][3]
                path_score += edge_data[(w, w_)][4]
                free_edges.remove((w, w_))

                r_path.append(rw_)
                r_path_edges.add((rw_, rw))
                r_path_length += edge_data[(rw_, rw)][3]
                r_path_score += edge_data[(rw_, rw)][4]
                free_edges.remove((rw_, rw))

                w = w_

            simple_paths[(v0, w0, path[-1])] = path_length, path_score, path
            r_path.reverse()
            assert r_path[0] == reverse_end(path[-1])
            simple_paths[(r_path[0], rw0, rv0)
                         ] = r_path_length, r_path_score, r_path

            LOG.debug(f"{path_length} {path_score} {path}")

            #dual_path[ (r_path[0], rw0, rv0) ] = (v0, w0, path[-1])
            #dual_path[ (v0, w0, path[-1]) ] = (r_path[0], rw0, rv0)
    return simple_paths


def identify_spurs(ug, u_edge_data, spur_len):
    # identify spurs in the utg graph
    # Currently, we use ad-hoc logic filtering out shorter utg, but we can
    # add proper alignment comparison later to remove redundant utgs
    # Side-effect: Modifies u_edge_data

    ug2 = ug.copy()

    s_candidates = set()
    for v in ug2.nodes():
        if ug2.in_degree(v) == 0:
            s_candidates.add(v)

    while len(s_candidates) > 0:
        n = s_candidates.pop()
        if ug2.in_degree(n) != 0:
            continue
        n_ego_graph = nx.ego_graph(ug2, n, radius=10)
        n_ego_node_set = set(n_ego_graph.nodes())
        for b_node in n_ego_graph.nodes():
            if ug2.in_degree(b_node) <= 1:
                continue

            with_extern_node = False
            b_in_nodes = [e[0] for e in ug2.in_edges(b_node)]

            if len(b_in_nodes) == 1:
                continue

            for v in b_in_nodes:
                if v not in n_ego_node_set:
                    with_extern_node = True
                    break

            if not with_extern_node:
                continue

            s_path = nx.shortest_path(ug2, n, b_node)
            v1 = s_path[0]
            total_length = 0
            for v2 in s_path[1:]:
                for s, t, v in ug2.out_edges(v1, keys=True):
                    if t != v2:
                        continue
                    length, score, edges, type_ = u_edge_data[(s, t, v)]
                    total_length += length
                v1 = v2

            if total_length >= spur_len:
                continue

            v1 = s_path[0]
            for v2 in s_path[1:]:
                for s, t, v in list(ug2.out_edges(v1, keys=True)):
                    if t != v2:
                        continue
                    length, score, edges, type_ = u_edge_data[(s, t, v)]
                    rs = reverse_end(t)
                    rt = reverse_end(s)
                    rv = reverse_end(v)
                    try:
                        ug2.remove_edge(s, t, key=v)
                        ug2.remove_edge(rs, rt, key=rv)
                        u_edge_data[(s, t, v)] = length, score, edges, "spur:2"
                        u_edge_data[(rs, rt, rv)
                                    ] = length, score, edges, "spur:2"
                    except Exception:
                        pass

                if ug2.in_degree(v2) == 0:
                    s_candidates.add(v2)
                v1 = v2
            break
    return ug2


def remove_dup_simple_path(ug, u_edge_data):
    # identify simple dup path
    # if there are many multiple simple path of length connect s and t, e.g.  s->v1->t, and s->v2->t, we will only keep one
    # Side-effect: Modifies u_edge_data
    ug2 = ug.copy()
    simple_edges = set()
    dup_edges = {}
    for s, t, v in u_edge_data:
        length, score, edges, type_ = u_edge_data[(s, t, v)]
        if len(edges) > 3:
            continue
        if type_ == "simple":
            if (s, t) in simple_edges:
                dup_edges[(s, t)].append(v)
            else:
                simple_edges.add((s, t))
                dup_edges[(s, t)] = [v]
    for (s, t) in dup_edges.keys():
        vl = dup_edges[(s, t)]
        vl.sort()
        for v in vl[1:]:
            ug2.remove_edge(s, t, key=v)
            length, score, edges, type_ = u_edge_data[(s, t, v)]
            u_edge_data[(s, t, v)] = length, score, edges, "simple_dup"
    return ug2


def construct_c_path_from_utgs(ug, u_edge_data, sg):
    # Side-effects: None, I think.

    s_nodes = set()
    simple_nodes = set()
    simple_out = set()

    all_nodes = ug.nodes()
    for n in all_nodes:
        in_degree = len(ug.in_edges(n))
        out_degree = len(ug.out_edges(n))
        if in_degree == 1 and out_degree == 1:
            simple_nodes.add(n)
        else:
            if out_degree != 0:
                s_nodes.add(n)
        if out_degree == 1:
            simple_out.add(n)

    c_path = []

    free_edges = set()
    for s, t, v in ug.edges(keys=True):
        free_edges.add((s, t, v))

    while free_edges:
        if s_nodes:
            n = s_nodes.pop()
        else:
            e = free_edges.pop()
            n = e[0]

        for s, t, v in ug.out_edges(n, keys=True):
            path_start = n
            path_end = None
            path_key = None
            path = []
            path_length = 0
            path_score = 0
            path_nodes = set()
            path_nodes.add(s)
            LOG.debug(f"check 1 {s} {t} {v}")
            path_key = t
            t0 = s
            while t in simple_out:
                if t in path_nodes:
                    break
                rt = reverse_end(t)
                if rt in path_nodes:
                    break

                length, score, path_or_edges, type_ = u_edge_data[(t0, t, v)]

                """
                If the next node has two in-edges and the current path has the best overlap,
                we will extend the contigs. Otherwise, we will terminate the contig extension.
                This can help reduce some mis-assemblies but it can still construct long contigs
                when there is an oppertunity (assuming the best overlap has the highest
                likelihood to be correct.)
                """
                if len(ug.in_edges(t, keys=True)) > 1:
                    best_in_node = sg.nodes[t]["best_in"]

                    if type_ == "simple" and best_in_node != path_or_edges[-2]:
                        break
                    if type_ == "compound":
                        t_in_nodes = set()
                        for ss, vv, tt in path_or_edges:
                            if tt != t:
                                continue
                            length, score, path_or_edges, type_ = u_edge_data[(
                                ss, vv, tt)]
                            if path_or_edges[-1] == tt:
                                t_in_nodes.add(path_or_edges[-2])
                        if best_in_node not in t_in_nodes:
                            break
                # ----------------

                path.append((t0, t, v))
                path_nodes.add(t)
                path_length += length
                path_score += score
                # t is "simple_out" node
                assert len(ug.out_edges(t, keys=True)) == 1
                t0, t, v = list(ug.out_edges(t, keys=True))[0]

            path.append((t0, t, v))
            length, score, path_or_edges, type_ = u_edge_data[(t0, t, v)]
            path_length += length
            path_score += score
            path_nodes.add(t)
            path_end = t

            c_path.append((path_start, path_key, path_end,
                           path_length, path_score, path, len(path)))
            LOG.debug(f"c_path {path_start} {path_key} {path_end} {path_length} {path_score} {len(path)}")
            for e in path:
                if e in free_edges:
                    free_edges.remove(e)

    LOG.debug(f"left over edges: {len(free_edges)}")
    return c_path

def extract_contigs(ug, u_edge_data, c_path, circular_path, ctg_prefix):
    free_edges = set()
    for s, t, v in ug.edges(keys=True):
        free_edges.add((s, t, v))

    ctg_id = 0

    for path_start, path_key, path_end, p_len, p_score, path, n_edges in c_path:
        length = 0
        score = 0
        length_r = 0
        score_r = 0

        non_overlapped_path = []
        non_overlapped_path_r = []
        for s, t, v in path:
            if v != "NA":
                rs, rt, rv = reverse_end(t), reverse_end(s), reverse_end(v)
            else:
                rs, rt, rv = reverse_end(t), reverse_end(s), "NA"
            if (s, t, v) in free_edges and (rs, rt, rv) in free_edges:
                non_overlapped_path.append((s, t, v))
                non_overlapped_path_r.append((rs, rt, rv))
                length += u_edge_data[(s, t, v)][0]
                score += u_edge_data[(s, t, v)][1]
                length_r += u_edge_data[(rs, rt, rv)][0]
                score_r += u_edge_data[(rs, rt, rv)][1]
            else:
                break

        if len(non_overlapped_path) == 0:
            continue
        s0, t0, v0 = non_overlapped_path[0]
        end_node = non_overlapped_path[-1][1]

        c_type_ = "ctg_linear" if (end_node != s0) else "ctg_circular"

        ctg_name = '%s%06dF' % (ctg_prefix, ctg_id)
        new_contig = (ctg_name, c_type_, s0 + "~" + v0 + "~" + \
                        t0, end_node, length, score, "|".join(
                        [c[0] + "~" + c[2] + "~" + c[1] for c in non_overlapped_path]))
        yield new_contig

        non_overlapped_path_r.reverse()
        s0, t0, v0 = non_overlapped_path_r[0]
        end_node = non_overlapped_path_r[-1][1]

        ctg_name = '%s%06dR' % (ctg_prefix, ctg_id)
        new_contig = (ctg_name, c_type_, s0 + "~" + v0 + "~" + \
                        t0, end_node, length_r, score_r, "|".join(
                        [c[0] + "~" + c[2] + "~" + c[1] for c in non_overlapped_path_r]))
        yield new_contig

        ctg_id += 1
        for e in non_overlapped_path:
            if e in free_edges:
                free_edges.remove(e)
        for e in non_overlapped_path_r:
            if e in free_edges:
                free_edges.remove(e)

    for s, t, v in list(circular_path):
        length, score, path, type_ = u_edge_data[(s, t, v)]
        ctg_name = '%s%d' % (ctg_prefix, ctg_id)
        new_contig = (ctg_name, "ctg_circular", s + \
                        "~" + v + "~" + t, t, length, score, s + "~" + v + "~" + t)
        yield new_contig
        ctg_id += 1

def identify_edges_to_remove(compound_paths, ug2):
    ug2_edges = set(ug2.edges(keys=True))
    edges_to_remove = set()
    with open("c_path", "w") as f:
        for s, v, t in compound_paths:
            width, length, score, bundle_edges = compound_paths[(s, v, t)]
            print(s, v, t, width, length, score, "|".join(
                [e[0] + "~" + e[2] + "~" + e[1] for e in bundle_edges]), file=f)
            for ss, tt, vv in bundle_edges:
                if (ss, tt, vv) in ug2_edges:
                    edges_to_remove.add((ss, tt, vv))
    return edges_to_remove

def identify_short_edges_to_remove(ug2, u_edge_data):
    edges_to_remove = set()
    for s, t, v in ug2.edges(keys=True):
        if ug2.in_degree(s) == 1 and ug2.out_degree(s) == 2 and \
            ug2.in_degree(t) == 2 and ug2.out_degree(t) == 1:
            length, score, path_or_edges, type_ = u_edge_data[(s, t, v)]
            if length < 60000:
                rs = reverse_end(t)
                rt = reverse_end(s)
                rv = reverse_end(v)
                edges_to_remove.add((s, t, v))
                edges_to_remove.add((rs, rt, rv))
    return edges_to_remove

def init_sg2(edge_data):
    sg2 = nx.DiGraph()
    for (v, w) in edge_data.keys():
        assert (reverse_end(w), reverse_end(v)) in edge_data
        # if (v, w) in masked_edges:
        #    continue
        rid, sp, tp, length, score, identity, type_ = edge_data[(v, w)]
        if type_ != "G":
            continue
        label = "%s:%d-%d" % (rid, sp, tp)
        sg2.add_edge(v, w, label=label, length=length, score=score)
    return sg2

def print_edge_data(u_edge_data):
    with open("utg_data", "w") as f:
        for s, t, v in u_edge_data:
            length, score, path_or_edges, type_ = u_edge_data[(s, t, v)]

            if v == "NA":
                path_or_edges = "|".join(
                    [ss + "~" + vv + "~" + tt for ss, tt, vv in path_or_edges])
            else:
                path_or_edges = "~".join(path_or_edges)
            print(s, v, t, type_, length, score, path_or_edges, file=f)

def print_utg_data0(u_edge_data):
    with open("utg_data0", "w") as f:
        for s, t, v in u_edge_data:
            rs = reverse_end(t)
            rt = reverse_end(s)
            rv = reverse_end(v)
            assert (rs, rt, rv) in u_edge_data
            length, score, path_or_edges, type_ = u_edge_data[(s, t, v)]

            if type_ == "compound":
                path_or_edges = "|".join(
                    [ss + "~" + vv + "~" + tt for ss, tt, vv in path_or_edges])
            else:
                path_or_edges = "~".join(path_or_edges)
            print(s, v, t, type_, length, score, path_or_edges, file=f)

def ovlp_to_graph(args):
    overlap_data = yield_from_overlap_file(args.overlap_file)

    # transitivity reduction
    sg = init_string_graph(overlap_data)

    # remove spurs, remove putative edges caused by repeats
    nxsg, edge_data = generate_nx_string_graph(sg, args.lfc, args.disable_chimer_bridge_removal)
    del sg, overlap_data

    #dual_path = {}
    nxsg2 = init_sg2(edge_data)

    ug = nx.MultiDiGraph()
    u_edge_data = {}
    circular_path = set()

    simple_paths = identify_simple_paths(nxsg2, edge_data)
    for s, v, t in simple_paths:
        length, score, path = simple_paths[(s, v, t)]
        u_edge_data[(s, t, v)] = (length, score, path, "simple")
        if s != t:
            ug.add_edge(s, t, key=v, type_="simple",
                        via=v, length=length, score=score)
        else:
            circular_path.add((s, t, v))

    if LOG.getEffectiveLevel() >= logging.DEBUG:
        print_utg_data0(u_edge_data)

    ug2 = identify_spurs(ug, u_edge_data, 50000)
    ug2 = remove_dup_simple_path(ug2, u_edge_data)

    # phase 2, finding all "consistent" compound paths
    compound_paths = construct_compound_paths(ug2, u_edge_data)
    edges_to_remove = identify_edges_to_remove(compound_paths, ug2)
    for s, t, v in edges_to_remove:
        ug2.remove_edge(s, t, v)
        length, score, edges, type_ = u_edge_data[(s, t, v)]
        if type_ != "spur":
            u_edge_data[(s, t, v)] = length, score, edges, "contained"

    for s, v, t in compound_paths:
        width, length, score, bundle_edges = compound_paths[(s, v, t)]
        u_edge_data[(s, t, v)] = (length, score, bundle_edges, "compound")
        ug2.add_edge(s, t, key=v, via=v, type_="compound",
                     length=length, score=score)

        assert v == "NA"
        rs = reverse_end(t)
        rt = reverse_end(s)
        assert (rs, v, rt) in compound_paths
        #dual_path[ (s, v, t) ] = (rs, v, rt)
        #dual_path[ (rs, v, rt) ] = (s, v, t)

    # remove short utg using local flow consistent rule
    r"""
      short UTG like this can be removed, this kind of utg are likely artifects of repeats
      >____           _____>
           \__UTG_>__/
      <____/         \_____<
    """
    short_edges_to_remove = identify_short_edges_to_remove(ug2, u_edge_data)
    for s, t, v in list(short_edges_to_remove):
        ug2.remove_edge(s, t, key=v)
        length, score, edges, type_ = u_edge_data[(s, t, v)]
        u_edge_data[(s, t, v)] = length, score, edges, "repeat_bridge"

    # Repeat the aggresive spur filtering with slightly larger spur length.
    ug = identify_spurs(ug2, u_edge_data, 80000)
    print_edge_data(u_edge_data)

    # contig construction from utgs
    c_path = construct_c_path_from_utgs(ug, u_edge_data, nxsg)

    # Sorting contig paths by length.
    c_path.sort(key=lambda x: -x[3])

    # Construct the contigs (based on unitigs).
    contigs = extract_contigs(ug, u_edge_data, c_path, circular_path, args.ctg_prefix)

    # Write contigs to file.
    with open('ctg_paths', 'w') as fp_out:
        for contig_tuple in contigs:
            fp_out.write(' '.join([str(val) for val in contig_tuple]))
            fp_out.write('\n')


class HelpF(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass

def main(argv=sys.argv):
    epilog = """
Outputs:
    - ctg_paths
    - c_path
    - sg_edges_list
    - chimer_nodes (if not --disable-chimer-bridge-removal)
    - utg_data
    - utg_data0 (maybe)
"""
    parser = argparse.ArgumentParser(
            description='example string graph assembler that is desinged for handling diploid genomes',
            epilog=epilog,
            formatter_class=HelpF)
    parser.add_argument(
        '--overlap-file', default='preads.m4',
        help='a file that contains the overlap information.')

    # These are only for the filter, currently a separate program. They are ignored here.
    parser.add_argument(
        '--min_len', type=int, default=4000,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--min-len', type=int, default=4000,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--min_idt', type=float, default=96,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--min-idt', type=float, default=96,
        help=argparse.SUPPRESS)

    parser.add_argument(
        '--lfc', action="store_true", default=False,
        help='use local flow constraint method rather than best overlap method to resolve knots in string graph')
    parser.add_argument(
        '--disable_chimer_bridge_removal', action="store_true", default=False,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '--disable-chimer-bridge-removal', action="store_true", default=False,
        help='disable chimer induced bridge removal')
    parser.add_argument(
        '--ctg-prefix', default='',
        help='Prefix for contig names.')

    args = parser.parse_args(argv[1:])
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(msg)s')
    ovlp_to_graph(args)


if __name__ == "__main__":
    main(sys.argv)

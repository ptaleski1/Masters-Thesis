import pandas as pd
import numpy as np
from datetime import datetime
from graph_tool.all import *
from dateutil.parser import parse
import matplotlib.pyplot as plt
from graph_tool.topology import label_components
from graph_tool import GraphView
import random
from scipy.stats import spearmanr, mannwhitneyu, pearsonr, norm
import sklearn
from sklearn.linear_model import LinearRegression
import math 
import os
from collections import defaultdict, Counter


#-------------File Paths-----------------------

path_dir = "processed_data"
results_dir = "results"

nodes_path = os.path.join(path_dir, "nodes.csv")
edges_path = os.path.join(path_dir, "edges.csv")
pr_output_file = os.path.join(results_dir, "MPPR_results")

nodes_df, edges_df = None, None

if os.path.exists(nodes_path) and os.path.exists(edges_path):
    nodes_df = pd.read_csv(nodes_path)
    edges_df = pd.read_csv(edges_path)
else:
    print("Nodes/edges CSVs not found — skipping load. They will be created later.")


# ---------Constant variables ---------------
lambda_decay = 0.24
core_dois = {
    "10.1126/science.1213362",
    "10.1038/nature10831",
    "10.1371/journal.pone.0188453",
    "10.1126/science.1072266",
    "10.1128/jvi.75.3.1205-1210.2001"
}

DAMPING = 0.85
ALPHAS = [0.85, 0.99, 0.50]      
BETAS = [3.0, 5.0, 7.0, 9.0]  # exponents for experiments 1a and 1b

# Node-type base scores 
SOURCE_TYPE_WEIGHTS = {
    "news_website": 8, "blog_post": 5, "wikipedia": 5, "video": 5,
    "policy_document": 3, "clinical_guidance": 3, "transcript": 1,
    "patent": 1, "academic_article": 1, "working_paper": 1, "preprint": 1,
    "book": 1, "book_chapter": 2, "report": 1, "editorial": 1, "review": 1,
    "letter": 1, "peer-review": 1, "dataset": 0.5, "guideline": 1,
    "dissertation": 0.5, "grant": 0.5,
    "paratext": 0.25, "periodical": 0.25, "reference-entry": 0.25, "retraction": 0.25, "erratum": 0.25,
    "other": 0.01
}

#-------------Functions-----------------------

def extract_year(date_str):
    """Return the 4-digit year parsed from a date-like string, or None if parsing fails."""
    try:
        return parse(date_str, fuzzy=True).year
    except:
        return None

def normalize_id(x):
    """Normalize an ID by casting to str, stripping whitespace, and lowercasing."""
    return str(x).strip().lower()

def bv_one_core(g, core_v):
    """Bias vector that puts all probability mass on a single core vertex."""
    bv = g.new_vertex_property("double")
    for v in g.vertices():
        bv[v] = 1.0 if v == core_v else 0.0
    return bv

def build_base_ppr_graph(
    nodes_df,
    edges_df,
    core_dois,
    lambda_decay,
    pr_output_file
):
    """Build a directed graph for PPR variants, run MPPR, and save results to CSV."""
    # Create graph 
    g = Graph(directed=True)
    v_id = g.new_vertex_property("string")
    v_year = g.new_vertex_property("int")
    v_title = g.new_vertex_property("string")
    v_infohaz_score = g.new_vertex_property("float")
    v_is_infohaz_related = g.new_vertex_property("bool")
    v_type = g.new_vertex_property("string")

    id_to_vertex = {}
    year_list = []
    now_year = datetime.now().year

    # Add vertices
    for _, row in nodes_df.iterrows():
        v = g.add_vertex()
        node_id = row["id"]
        id_to_vertex[node_id] = v
        v_id[v] = node_id
        v_title[v] = row.get("title", "")
        v_type[v] = row.get("node_type", "")
        year = extract_year(str(row.get("publication_date", "")))
        v_year[v] = year if year else -1
        if year: year_list.append(year)
        score = float(row.get("score", 0.0))
        v_infohaz_score[v] = score
        v_is_infohaz_related[v] = score >= 7.0

    g.vertex_properties["id"] = v_id

    # Fill missing years
    avg_year = int(np.mean(year_list)) if year_list else now_year
    for v in g.vertices():
        if v_year[v] == -1:
            v_year[v] = avg_year

    fallback_year = avg_year  
    e_weight = g.new_edge_property("double")

    # Add edges
    for _, row in edges_df.iterrows():
        source_id = row["source_id"]  # citer
        target_id = row["target_id"]  # cited
        src = id_to_vertex[source_id]
        tgt = id_to_vertex[target_id]
        e = g.add_edge(tgt, src)  # reverse: cited -> citer
        base_w = float(row.get("weighting", 1.0))  
        citer_year = int(v_year[src]) if int(v_year[src]) > 0 else fallback_year
        age = max(0, now_year - citer_year)
        w = base_w
        e_weight[e] = w 

    g.edge_properties["weight"] = e_weight

    # Register vertex properties 
    g.vertex_properties["id"] = v_id
    g.vertex_properties["year"] = v_year
    g.vertex_properties["title"] = v_title
    g.vertex_properties["score"] = v_infohaz_score
    g.vertex_properties["is_infohazard_related"] = v_is_infohaz_related
    g.vertex_properties["type"] = v_type

    print(f"Final node count: {g.num_vertices()}")
    print(f"Final edge count: {g.num_edges()}")

    # Connectivity check 
    print("Checking connectivity of 'g'")
    g_undirected = GraphView(g, directed=False)
    _, component_hist = label_components(g_undirected, directed=False)
    print(f"Number of weakly connected components: {len(component_hist)}")
    if len(component_hist) > 1:
        print("Warning: Graph is disconnected — some nodes may be isolated or unreachable.")

    # Identify core nodes 
    core_vertices = [v for v in g.vertices() if v_id[v] in core_dois]
    # Force all core papers to be "infohazard related"
    for v in core_vertices:
        v_is_infohaz_related[v] = True

    core_set = set(core_vertices)
    alpha_layer = 0.85  # damping for the layer-score PPR (unweighted)

    runs = []
    for c in core_vertices:
        bv_c = bv_one_core(g, c)
        pr_c = pagerank(g, damping=alpha_layer, weight=None, pers=bv_c)
        arr = np.array([pr_c[v] for v in g.vertices()], dtype=float)
        # zero out the prob mass for core for this run (no self-inflation)
        arr[int(c)] = 0.0
        runs.append(arr)

    avg = np.mean(np.vstack(runs), axis=0)

    # Min–max normalise over ALL nodes (cores included)
    mn, mx = float(np.min(avg)), float(np.max(avg))
    den = (mx - mn) if (mx > mn) else 1.0
    norm = (avg - mn) / den

    # Write to vertex property
    v_layer_score = g.new_vertex_property("float")
    for v, val in zip(g.vertices(), norm):
        v_layer_score[v] = float(val)

    # Save to graph
    g.vp["layer_score"] = v_layer_score

    # Time-decay and normalize 
    bias_vector = g.new_vertex_property("double")
    for v in g.vertices():
        age = now_year - v_year[v]
        decay = np.exp(-lambda_decay * age)
        bias_vector[v] = v_layer_score[v] * decay

    bv_sum = sum(bias_vector[v] for v in g.vertices())
    for v in g.vertices():
        bias_vector[v] = bias_vector[v] / bv_sum if bv_sum > 0 else 0.0

    # Run MPPR
    pr_scores, num_iterations = pagerank(
        g,
        damping=DAMPING,
        weight=e_weight,
        pers=bias_vector,
        ret_iter=True
    )

    # Collect results 
    results = [{
        "id": v_id[v],
        "title": v_title[v],
        "node_type": v_type[v],
        "pagerank": pr_scores[v],
        "year": v_year[v],
        "layer_score": v_layer_score[v],
        "infohazard_relevance_score": v_infohaz_score[v],
        "is_infohazard_related": bool(v_is_infohaz_related[v])
    } for v in g.vertices()]

    pr_df = pd.DataFrame(results).sort_values("pagerank", ascending=False)
    pr_df["rank"] = pr_df["pagerank"].rank(ascending=False)
    N = len(pr_df)
    pr_df["percentile_rank"] = ((pr_df["rank"] - 1) / N) * 100

    pr_df.to_csv(pr_output_file, index=False, encoding="utf-8-sig")
    print(f"PPR converged in {num_iterations} iterations.")
    print(f"Saved results to: {pr_output_file}\n")

    return g, e_weight, bias_vector, pr_scores, pr_df, num_iterations

# Run PageRank (other variants)
def run_pagerank(g, weight=None, pers=None):
    """Run weighted Personalized PageRank with shared damping factor."""
    return pagerank(g, damping=DAMPING, weight=weight, pers=pers)

def build_uniform_bias_vector(g):
    """Create a uniform bias vector where each vertex has equal probability mass."""
    bv = g.new_vertex_property("double")
    for v in g.vertices():
        bv[v] = 1.0
    total = sum(bv[v] for v in g.vertices())
    for v in g.vertices():
        bv[v] /= total
    return bv

def build_random_bias_vector(g):
    """Create a bias vector with random values normalized to sum to 1."""
    bv = g.new_vertex_property("double")
    for v in g.vertices():
        bv[v] = np.random.rand()
    total = sum(bv[v] for v in g.vertices())
    for v in g.vertices():
        bv[v] /= total
    return bv

def top_overlap(df_var, df_ref, k):
    """Compute overlap of top-k nodes by rank between variant and reference."""
    A = set(df_var.nsmallest(k, "rank")["id"])
    B = set(df_ref.nsmallest(k, "rank")["id"])
    return len(A & B) / float(k)

def df_from_scores(g, scores_prop):
    """Convert a scores property map into a ranked DataFrame with percentile ranks."""
    ids = [g.vp["id"][v] for v in g.vertices()]
    scores = [float(scores_prop[v]) for v in g.vertices()]
    is_ih = [bool(g.vp["is_infohazard_related"][v]) for v in g.vertices()]
    df = pd.DataFrame({"id": ids, "score": scores, "is_infohaz": is_ih})
    df["rank"] = df["score"].rank(ascending=False, method="average")
    N = len(df)
    df["percentile_rank"] = ((df["rank"] - 1) / N) * 100
    return df

# Overlaps
def comp_ov(dfA, dfB, k):
    """Compute overlap of top-k ranked nodes between two DataFrames."""
    A = set(dfA.nsmallest(k, "rank")["id"])
    B = set(dfB.nsmallest(k, "rank")["id"])
    return len(A & B) / float(k)

# Summary (vs Baseline: UNW + Uniform BV)
def summarize_variant(name, scores_prop, ref_scores_prop, g):
    """Summarize a PR variant vs baseline: overlaps, IH enrichment, deltas, Spearman, and effect sizes."""
    df_var = df_from_scores(g, scores_prop)
    df_ref = df_from_scores(g, ref_scores_prop)  

    # align on id for rank–rank Spearman
    ref_rank = df_ref[["id", "rank"]].rename(columns={"rank": "ref_rank"})
    df = df_var.merge(ref_rank, on="id", how="left")

    n = len(df)
    k100  = min(100, n)
    k500  = min(500, n)
    k1pct = max(1, int(0.01 * n))
    k5pct = max(1, int(0.05 * n))

    # IH enrichment (variant)
    top100_IH_pct  = 100.0 * df.nsmallest(k100, "rank")["is_infohaz"].mean()
    top500_IH_pct  = 100.0 * df.nsmallest(k500, "rank")["is_infohaz"].mean()
    top1pct_IH_pct = 100.0 * df.nsmallest(k1pct, "rank")["is_infohaz"].mean()
    top5pct_IH_pct = 100.0 * df.nsmallest(k5pct, "rank")["is_infohaz"].mean()

    avg_ih_rank_pct = (
        float(df.loc[df["is_infohaz"], "percentile_rank"].mean())
        if df["is_infohaz"].any() else np.nan
    )

    # IH enrichment (baseline)
    ref_top100_IH_pct = 100.0 * df_ref.nsmallest(k100, "rank")["is_infohaz"].mean()
    ref_avg_ih_rank_pct = (
        float(df_ref.loc[df_ref["is_infohaz"], "percentile_rank"].mean())
        if df_ref["is_infohaz"].any() else np.nan
    )

    # Deltas vs baseline
    delta_top100_vs_base = round(top100_IH_pct - ref_top100_IH_pct, 2)
    delta_avgih_vs_base = (
        round(avg_ih_rank_pct - ref_avg_ih_rank_pct, 2)
        if not (pd.isna(avg_ih_rank_pct) or pd.isna(ref_avg_ih_rank_pct)) else np.nan
    )

    # Spearman vs baseline
    if df["rank"].nunique() > 1 and df["ref_rank"].nunique() > 1:
        rho, pval = spearmanr(df["rank"], df["ref_rank"])
    else:
        rho, pval = None, None

    ov100  = round(comp_ov(df_var, df_ref, k100) * 100, 2)
    ov500  = round(comp_ov(df_var, df_ref, k500) * 100, 2)
    ov1pct = round(comp_ov(df_var, df_ref, k1pct) * 100, 2)
    ov5pct = round(comp_ov(df_var, df_ref, k5pct) * 100, 2)

    # MWU / effect size 
    ih_sample  = df.loc[df["is_infohaz"],  "percentile_rank"].to_numpy()
    non_sample = df.loc[~df["is_infohaz"], "percentile_rank"].to_numpy()
    # mwu_U = mwu_p = mwu_r = None
    mwu_U = mwu_p = cles = cliffs_delta = None
    if len(ih_sample) > 0 and len(non_sample) > 0:
        res = mannwhitneyu(ih_sample, non_sample, alternative="two-sided", method="asymptotic")
        mwu_U = float(res.statistic)
        mwu_p = float(res.pvalue)

        n1, n2 = len(ih_sample), len(non_sample)

        # Vargha & Delaney’s A (VDA)
        vda = mwu_U / (n1 * n2)

        # Cliff’s delta (linearly related to VDA)
        cliffs_delta = 2 * vda - 1

    return {
        "Variant": name,
        "Spearman": round(rho, 2) if rho is not None else None,
        "spearman_p": pval,
        "Overlap top_100 (%)": round(ov100, 2),
        "Overlap top_500 (%)": round(ov500, 2),
        "Overlap top 1pct (%)": round(ov1pct, 2),
        "Overlap top 5pct (%)": round(ov5pct, 2),
        "Top_100 IH_pct (%)": round(top100_IH_pct, 2),
        "Δ top 100 (%)": round(delta_top100_vs_base, 2),
        "Average IH percentile rank (AIHPR)": round(avg_ih_rank_pct, 2) if not pd.isna(avg_ih_rank_pct) else np.nan,
        "Δ AIHPR (%)": round(delta_avgih_vs_base, 2),
        "Top_500 IH_pct (%)": round(top500_IH_pct, 2),
        "Top 1pct_IH (%)": round(top1pct_IH_pct, 2),
        "Top 5pct_IH (%)": round(top5pct_IH_pct, 2),
        "Mann-Whitney U": round(mwu_U, 2),
        "Mann-Whitney P": mwu_p,
        "Effect size (\delta)": round(cliffs_delta, 2),
    }

def build_bv_layer_only(g):
    """Build a bias vector proportional to layer_score only (no time/type), normalized."""
    v_layer = ensure_layer_score(g, core_dois) 
    bv = g.new_vertex_property("double")
    tot = 0.0
    for v in g.vertices():
        val = float(v_layer[v])
        bv[v] = val; tot += val
    if tot > 0:
        for v in g.vertices():
            bv[v] /= tot
    return bv


def build_bv_time_only(g, lambda_node=lambda_decay):
    """Build a bias vector using only node age via exp(-λ·age), normalized."""
    v_year = g.vp["year"]
    now = datetime.now().year
    bv = g.new_vertex_property("double")
    tot = 0.0
    for v in g.vertices():
        age = max(0, now - int(v_year[v]))
        val = math.exp(-lambda_node * age)
        bv[v] = val; tot += val
    if tot > 0:
        for v in g.vertices():
            bv[v] /= tot
    return bv

def build_bv_type_only(g):
    """Build a bias vector from node-type priors (SOURCE_TYPE_WEIGHTS), normalized."""
    v_type = g.vp["type"]
    bv = g.new_vertex_property("double")
    tot = 0.0
    for v in g.vertices():
        t = str(v_type[v]).strip().lower()
        base = SOURCE_TYPE_WEIGHTS.get(t, 1.0)
        val = float(base)
        bv[v] = val; tot += val
    if tot > 0:
        for v in g.vertices(): bv[v] = bv[v] / tot
    return bv


def mwv(g, pr_layer, pr_time, mix_weight=0.5):
    """Compute Mixed-weight variant by mixing two PR vectors: w·PR_layer + (1−w)·PR_time."""
    pr_mix = g.new_vertex_property("double")
    for v in g.vertices():
        pr_mix[v] = mix_weight * float(pr_layer[v]) + (1.0 - mix_weight) * float(pr_time[v])
    return pr_mix

def run_all_variants(g, bias_vector, e_weight, pr_scores):
    """Run baseline and multiple PPR variants, summarize vs baseline, and return (summary_df, scores_dict, baseline)."""
    rows = []
    variant_scores = {}

    # --- Baseline: UNW + Uniform BV ---
    bv_uniform  = build_uniform_bias_vector(g)
    pr_baseline = run_pagerank(g, weight=None, pers=bv_uniform)

    # Baseline row (self vs self)
    rows.append(summarize_variant("Baseline", pr_baseline, pr_baseline, g))
    variant_scores["Baseline"] = pr_baseline

    # --- MPPR (vs baseline) ---
    rows.append(summarize_variant("MPPR", pr_scores, pr_baseline, g))
    variant_scores["MPPR"] = pr_scores

    # --- Weighted + uniform BV---
    pr_uniform_weighted = run_pagerank(g, weight=e_weight, pers=bv_uniform)
    rows.append(summarize_variant("W+UBV", pr_uniform_weighted, pr_baseline, g))
    variant_scores["W+UBV"] = pr_uniform_weighted

    # --- Unweighted + MPPR BV ---
    pr_unweighted = run_pagerank(g, weight=None, pers=bias_vector)
    rows.append(summarize_variant("UNW+MBV", pr_unweighted, pr_baseline, g))
    variant_scores["UNW+MBV"] = pr_unweighted

    # --- Weighted + random BV ---
    bv_random = build_random_bias_vector(g)
    pr_random = run_pagerank(g, weight=e_weight, pers=bv_random)
    rows.append(summarize_variant("W+RBV", pr_random, pr_baseline, g))
    variant_scores["W+RBV"] = pr_random

    # --- Weighted + Layer-only BV ---
    bv_layer = build_bv_layer_only(g)
    pr_layer = run_pagerank(g, weight=e_weight, pers=bv_layer)
    rows.append(summarize_variant("W+LBV", pr_layer, pr_baseline, g))
    variant_scores["W+LBV"] = pr_layer

    # --- Weighted + Time-only BV ---
    bv_time = build_bv_time_only(g, lambda_node=lambda_decay)
    pr_time = run_pagerank(g, weight=e_weight, pers=bv_time)
    rows.append(summarize_variant("W+DBV", pr_time, pr_baseline, g))
    variant_scores["W+DBV"] = pr_time

    # --- Weighted + Topic-Sensitive PR mixtures (post-PR run mixing) ---
    for mix_weight in [0.25, 0.5, 0.75]:
        pr_mix = mwv(g, pr_layer, pr_time, mix_weight=mix_weight)
        label = f"W+MWBV_{mix_weight}"
        rows.append(summarize_variant(label, pr_mix, pr_baseline, g))
        variant_scores[label] = pr_mix

    # --- Weighted + Type-only BV ---
    bv_type = build_bv_type_only(g)  
    pr_type = run_pagerank(g, weight=e_weight, pers=bv_type)
    rows.append(summarize_variant("W+TBV", pr_type, pr_baseline, g))
    variant_scores["W+TBV"] = pr_type

    summary_internal = pd.DataFrame(rows)
    return summary_internal, variant_scores, pr_baseline


def compare_directional_graph(
    edges_df, nodes_df, core_dois, pr_scores,
    label="Rev+MBV"
):
    """
    Build a graph with edge orientation citing->cited, 
    MPPR-style bias vector, and summarize vs a baseline.
    """
    # Normalize IDs
    nodes_df["id"] = nodes_df["id"].apply(normalize_id)
    edges_df["source_id"] = edges_df["source_id"].apply(normalize_id)
    edges_df["target_id"] = edges_df["target_id"].apply(normalize_id)

    # Create Graph (direction reversed)
    g_dir = Graph(directed=True)
    v_id_dir = g_dir.new_vertex_property("string")
    v_year_dir = g_dir.new_vertex_property("int")
    v_title_dir = g_dir.new_vertex_property("string")
    v_score_dir = g_dir.new_vertex_property("float")
    v_ih_dir = g_dir.new_vertex_property("bool")
    v_type_dir = g_dir.new_vertex_property("string")

    id_to_vertex_dir = {}
    year_list = []
    now_year = datetime.now().year

    for _, row in nodes_df.iterrows():
        v = g_dir.add_vertex()
        node_id = row["id"]
        id_to_vertex_dir[node_id] = v
        v_id_dir[v] = node_id
        v_title_dir[v] = row.get("title", "")
        v_type_dir[v] = row.get("node_type", "")
        year = extract_year(str(row.get("publication_date", "")))
        v_year_dir[v] = year if year else -1
        if year:
            year_list.append(year)
        score = float(row.get("score", 0.0))
        v_score_dir[v] = score
        v_ih_dir[v] = score >= 7.0


    g_dir.vertex_properties["id"] = v_id_dir
    g_dir.vertex_properties["is_infohazard_related"] = v_ih_dir

    # Fill Missing Years
    avg_year = int(np.mean(year_list))
    for v in g_dir.vertices():
        if v_year_dir[v] == -1:
            v_year_dir[v] = avg_year

    
    e_weight_dir = g_dir.new_edge_property("double")
    missing = 0
    
    for _, row in edges_df.iterrows():
        src_id = row["source_id"]   # citer
        tgt_id = row["target_id"]   # cited
        if src_id not in id_to_vertex_dir or tgt_id not in id_to_vertex_dir:
            missing += 1
            continue
    
        src = id_to_vertex_dir[src_id]
        tgt = id_to_vertex_dir[tgt_id]
        e = g_dir.add_edge(src, tgt)
    
        base_w = float(row.get("weighting", 1.0))
    
        citer_year = int(v_year_dir[src])

        age = max(0, now_year - citer_year)
    
        w_dir = base_w 
        e_weight_dir[e] = w_dir 
    
    g_dir.edge_properties["weight"] = e_weight_dir

    g_dir.vertex_properties["id"] = v_id_dir
    g_dir.vertex_properties["title"] = v_title_dir
    g_dir.vertex_properties["type"] = v_type_dir
    g_dir.vertex_properties["year"] = v_year_dir
    g_dir.vertex_properties["score"] = v_score_dir
    g_dir.vertex_properties["is_infohazard_related"] = v_ih_dir
    
    print(f"[g_dir] Skipped {missing} edges due to missing nodes.")
    print(f"[g_dir] Final node count: {g_dir.num_vertices()}")
    print(f"[g_dir] Final edge count: {g_dir.num_edges()}")

    # Core node mapping
    core_vertices = [v for v in g_dir.vertices() if v_id_dir[v] in core_dois]
    core_set = set(core_vertices)
    
    # Force all core papers to be "infohazard related"
    for v in g_dir.vertices():
        if v_id_dir[v] in core_set:
            v_ih_dir[v] = True

    alpha_layer = 0.85  # damping for layer-score PPR (unweighted)

    runs = []
    for c in core_vertices:
        bv_c = bv_one_core(g_dir, c)
        pr_c = pagerank(g_dir, damping=alpha_layer, weight=None, pers=bv_c)
        arr = np.array([pr_c[v] for v in g_dir.vertices()], dtype=float)
        arr[int(c)] = 0.0  # prevent core self-inflation in its own run
        runs.append(arr)

    # Average across per-core runs (cores exist by design)
    avg = np.mean(np.vstack(runs), axis=0)

    # Min–max normalise over ALL nodes (cores included)
    mn, mx = float(np.min(avg)), float(np.max(avg))
    den = (mx - mn) if (mx > mn) else 1.0
    norm = (avg - mn) / den

    # Write to vertex property on g_dir
    v_layer_score = g_dir.new_vertex_property("float")
    for v, val in zip(g_dir.vertices(), norm):
        v_layer_score[v] = float(val)

    g_dir.vp["layer_score"] = v_layer_score

    # Time decay and normalize
    bias_vector = g_dir.new_vertex_property("double")
    for v in g_dir.vertices():
        age = now_year - v_year_dir[v]
        decay = np.exp(-lambda_decay * age)
        bias_vector[v] = v_layer_score[v] * decay
    bv_sum = sum(bias_vector[v] for v in g_dir.vertices())
    for v in g_dir.vertices():
        bias_vector[v] = bias_vector[v] / bv_sum if bv_sum > 0 else 0.0

    # Run PageRank
    pr_dir = pagerank(g_dir, damping=DAMPING, weight=e_weight_dir, pers=bias_vector)

    # Evaluate against baseline
    metrics_directional = summarize_variant(
        name=label,
        scores_prop=pr_dir,        
        ref_scores_prop=pr_scores, 
        g=g_dir
    )

    return pr_dir, metrics_directional, g_dir


def scores_series(g, scores):
    """Return a pandas Series of PR scores keyed by node ID."""
    return pd.Series({g.vp["id"][v]: float(scores[v]) for v in g.vertices()})

def analyze_structural_baseline(
    g,
    reference_scores,                  
    label="UUW+UBV",
    alpha=DAMPING
):
    """Run PR on an undirected, unweighted, uniform-bias baseline and summarize vs baseline."""
    # 1) Undirected view of the SAME graph (keeps vertex identity alignment)
    g_undirected = GraphView(g, directed=False)

    # 2) Uniform bias vector on the undirected view (normalized)
    bv_uniform = g_undirected.new_vertex_property("double")
    for v in g_undirected.vertices():
        bv_uniform[v] = 1.0
    total = sum(bv_uniform[v] for v in g_undirected.vertices())
    if total > 0:
        for v in g_undirected.vertices():
            bv_uniform[v] /= total

    # 3) Run PageRank (unweighted) on the structural baseline
    pr_struct = pagerank(g_undirected, damping=alpha, weight=None, pers=bv_uniform)

    # 4) Summarize vs baseline
    metrics = summarize_variant(
        name=label,
        scores_prop=pr_struct,
        ref_scores_prop=reference_scores,
        g=g_undirected
    )

    return pr_struct, metrics

def pct_to_k(g, pct):
    """Convert a percent (e.g., 0.01 for 1%) to a top-k count (at least 1)."""
    return max(1, int(np.ceil(pct * g.num_vertices())))

def safe_display(df, title=None):
    """Display a DataFrame if possible; fall back to print on error."""
    try:
        from IPython.display import display
        if title: print(title)
        display(df)
    except Exception:
        if title: print(title)
        print(df)

def ensure_layer_score(g, core_ids, alpha=0.85):
    """Compute/attach per-core unweighted PPR layer_score (self-zeroed, min–max normalized)."""
    # Return existing if already computed
    if "layer_score" in g.vp:
        return g.vp["layer_score"]

    v_id = g.vp["id"]
    cores = [v for v in g.vertices() if v_id[v] in core_ids]

    # Run unweighted PPR once per core, zero that core, collect as arrays
    runs = []
    for c in cores:
        bv_c = bv_one_core(g, c)
        ppr_c = pagerank(g, damping=alpha, weight=None, pers=bv_c)
        arr = np.array([ppr_c[v] for v in g.vertices()], dtype=float)
        arr[int(c)] = 0.0  # no self-inflation for the seed core
        runs.append(arr)

    # Average across cores (cores exist by design)
    avg = np.mean(np.vstack(runs), axis=0)

    # Min–max normalise over ALL nodes so cores can be >0 if other cores reach them
    mn, mx = float(np.min(avg)), float(np.max(avg))
    denom = (mx - mn) if (mx > mn) else 1.0
    norm = (avg - mn) / denom

    # Write to vertex property
    v_layer = g.new_vertex_property("float")
    for v, val in zip(g.vertices(), norm):
        v_layer[v] = float(val)

    g.vp["layer_score"] = v_layer
    return v_layer

def build_bv_layer_time(g, lambda_node=lambda_decay):
    """Bias: layer_score × node time-decay, normalized. MPPR bias vector"""
    v_year = g.vp["year"]
    v_layer = ensure_layer_score(g, core_dois) 
    now = datetime.now().year
    bv = g.new_vertex_property("double")
    tot = 0.0
    for v in g.vertices():
        age = max(0, now - int(v_year[v]))
        val = float(v_layer[v]) * math.exp(-lambda_node * age)
        bv[v] = val; tot += val
    if tot > 0:
        for v in g.vertices(): bv[v] = bv[v] / tot
    return bv

def make_edge_weights(
    g,
    variant="UNW",
    lambda_edge=lambda_decay,
    beta=None,          
    use_layer=False,
    use_type=False,
):
    """Construct edge-weight property for variants (UNW, BW, BW_TD, EXP) with optional layer/type mods."""
    if variant == "UNW":
        return None

    base_prop = g.ep["weight"] if "weight" in g.ep else None
    v_year  = g.vp["year"]
    v_type  = g.vp["type"]
    v_layer = ensure_layer_score(g, core_dois) 
    type_map = {k.lower(): v for k, v in SOURCE_TYPE_WEIGHTS.items()}
    now = datetime.now().year

    e_w = g.new_edge_property("double")
    for e in g.edges():
        base = float(base_prop[e]) if base_prop is not None else 1.0
        citer = e.target()
        age = max(0, now - int(v_year[citer]))
        td  = math.exp(-lambda_edge * age)

        mult = 1.0
        if use_layer:
            mult *= float(v_layer[citer])
        if use_type:
            mult *= float(type_map.get(str(v_type[citer]).strip().lower(), 1.0))

        if variant == "BW":
            w = base * mult
        elif variant == "BW_TD":
            w = base * td * mult
        elif variant == "EXP":
            if beta is None:
                raise ValueError("beta must be provided for EXP variant")
            w = (base * td * mult) ** float(beta)
        else:
            w = base * mult

        if not np.isfinite(w) or w <= 0:
            w = 1e-12
        e_w[e] = float(w)
    return e_w

def run_ppr(g, alpha, weight_prop, bv_prop):
    """Run PageRank with given damping, edge weights, and personalization vector."""
    return pagerank(g, damping=alpha, weight=weight_prop, pers=bv_prop)

def scores_to_series(g, propmap):
    """Convert a vertex PropertyMap of scores to a pandas Series (vertex order)."""
    return pd.Series([float(propmap[v]) for v in g.vertices()])

def spearman_vs(g, a_scores, b_scores):
    """Compute Spearman correlation between two PR score vectors on the same graph."""
    a = scores_to_series(g, a_scores).rank(ascending=False, method="average")
    b = scores_to_series(g, b_scores).rank(ascending=False, method="average")
    return float(a.corr(b, method="spearman"))

def top_overlap(g, a_scores, b_scores, k):
    """Overlap@k between two PR vectors (by top-k sets of vertices)."""
    order_a = sorted(list(g.vertices()), key=lambda x: float(a_scores[x]), reverse=True)[:k]
    order_b = sorted(list(g.vertices()), key=lambda x: float(b_scores[x]), reverse=True)[:k]
    # Use vertex indices (stable) for set intersection
    A = set(int(v) for v in order_a)
    B = set(int(v) for v in order_b)
    return len(A & B) / float(k)

def ih_metrics(g, scores_prop, k):
    """Return IH percentage in top-k and a breakdown of IH node types."""
    v_ih = g.vp["is_infohazard_related"]; v_type = g.vp["type"]
    order = sorted(list(g.vertices()), key=lambda x: float(scores_prop[x]), reverse=True)[:k]
    flags = [bool(v_ih[v]) for v in order]
    pct = 100.0 * (sum(flags) / max(1, len(flags)))
    ih_types = [str(v_type[v]) for v, ok in zip(order, flags) if ok]
    if ih_types:
        bd = (pd.Series(ih_types).value_counts(dropna=False)
              .to_frame("count")
              .assign(share=lambda df: (df["count"] / df["count"].sum()).round(3)))
    else:
        bd = pd.DataFrame(columns=["count","share"])
    return pct, bd

def cmp_vs_baseline(g, baseline_scores, model_scores, k100, k500, k1pct, k5pct):
    """Compare a model to baseline using Spearman and overlap@k metrics."""
    return {
        "spearman": round(spearman_vs(g, baseline_scores, model_scores), 6),
        "overlap@100": round(top_overlap(g, baseline_scores, model_scores, k100), 3),
        "overlap@500": round(top_overlap(g, baseline_scores, model_scores, k500), 3),
        "overlap@1pct": round(top_overlap(g, baseline_scores, model_scores, k1pct), 3),
        "overlap@5pct": round(top_overlap(g, baseline_scores, model_scores, k5pct), 3),
    }

def ih_pct_for(scores):
    """Compute IH % at several top-k cutoffs using outer-scope g/k* variables."""
    ih100, _ = ih_metrics(g, scores, k100)
    ih500, _ = ih_metrics(g, scores, k500)
    ih1p , _ = ih_metrics(g, scores, k1pct)
    ih5p , _ = ih_metrics(g, scores, k5pct)
    return dict(
        top100_IH_pct=round(ih100, 2),
        top500_IH_pct=round(ih500, 2),
        top1pct_IH_pct=round(ih1p, 2),
        top5pct_IH_pct=round(ih5p, 2),
    )

def compute_ppr_scores(g, bv_vec, weighted, alpha, label):
    """Run PPR for a given BV/weighting and report IH% in top-k bands."""
    edge_weight = g.ep["weight"] if weighted else None
    pr = pagerank(g, damping=alpha, weight=edge_weight, pers=bv_vec)

    scores = np.array([float(pr[v]) for v in g.vertices()])
    is_ih = np.array([bool(g.vp["is_infohazard_related"][v]) for v in g.vertices()], dtype=bool)

    n_total = scores.size
    k100  = min(100, n_total)
    k500  = min(500, n_total)
    k1pct = max(1, int(0.01 * n_total))
    k5pct = max(1, int(0.05 * n_total))

    order = np.argsort(scores)[::-1]

    top100_IH_pct  = 100.0 * is_ih[order[:k100]].mean()
    top500_IH_pct  = 100.0 * is_ih[order[:k500]].mean()
    top1pct_IH_pct = 100.0 * is_ih[order[:k1pct]].mean()
    top5pct_IH_pct = 100.0 * is_ih[order[:k5pct]].mean()

    return {
        "Label": label,
        "IH % (Top 100)": round(top100_IH_pct, 2),
        "IH % (Top 500)": round(top500_IH_pct, 2),
        "IH % (Top 1%)": round(top1pct_IH_pct, 2),
        "IH % (Top 5%)": round(top5pct_IH_pct, 2),
    }

def compute_ppr_scores_from_pr(g, pr, label):
    """Report IH% in top-k bands for an existing PPR variant (no PR run)."""
    scores = np.array([float(pr[v]) for v in g.vertices()])
    is_ih = np.array([bool(g.vp["is_infohazard_related"][v]) for v in g.vertices()], dtype=bool)

    n_total = scores.size
    k100  = min(100, n_total)
    k500  = min(500,  n_total)
    k1pct = max(1, math.ceil(0.01 * n_total))
    k5pct = max(1, math.ceil(0.05 * n_total))

    order = np.argsort(scores)[::-1]

    top100_IH_pct  = 100.0 * is_ih[order[:k100]].mean()
    top500_IH_pct  = 100.0 * is_ih[order[:k500]].mean()
    top1pct_IH_pct = 100.0 * is_ih[order[:k1pct]].mean()
    top5pct_IH_pct = 100.0 * is_ih[order[:k5pct]].mean()

    return {
        "Label": label,
        "IH % (Top 100)": round(top100_IH_pct, 2),
        "IH % (Top 500)": round(top500_IH_pct, 2),
        "IH % (Top 1%)":  round(top1pct_IH_pct, 2),
        "IH % (Top 5%)":  round(top5pct_IH_pct, 2),
    }

def run_ih_enrichment_vs_mppr(
    g,
    pr_main,                 
    alpha=DAMPING,
    variants=None,         
    results_dir=".",
    outfile="Exp_3a_ih_enrichment_vs_MPPR.csv"
):
    """Compare IH% bands of variants vs MPPR baseline and write a results CSV."""

    if variants is None:
        variants = []

    rows = []

    # Baseline: MPPR 
    rows.append(compute_ppr_scores_from_pr(g, pr_main, label="MPPR"))

    # Variants
    for spec in variants:
        label = spec["label"]
        if "pr" in spec and spec["pr"] is not None:
            rows.append(compute_ppr_scores_from_pr(g, spec["pr"], label=label))
        elif "bv" in spec:
            weighted = bool(spec.get("weighted", True))
            rows.append(compute_ppr_scores(g, spec["bv"], weighted=weighted, alpha=alpha, label=label))
        else:
            raise ValueError(f"Variant '{label}' must have either 'pr' or 'bv'.")

    df = pd.DataFrame(rows)

    # Add Δ vs baseline columns 
    base = df.iloc[0]
    for col in ["IH % (Top 100)", "IH % (Top 500)", "IH % (Top 1%)", "IH % (Top 5%)"]:
        df[f"Δ {col}"] = (df[col] - float(base[col])).round(2)

    ordered = [
        "Label",
        "IH % (Top 100)", "IH % (Top 500)", "IH % (Top 1%)", "IH % (Top 5%)",
        "Δ IH % (Top 100)", "Δ IH % (Top 500)",
        "Δ IH % (Top 1%)",  "Δ IH % (Top 5%)",
    ]
    df = df[ordered]

    out_path = os.path.join(results_dir, outfile)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"IH enrichment results (vs MPPR) saved to {out_path}")

    return df

# -- Helper to convert PR scores to a tidy DF
def pr_to_df(g, pr_scores):
    """Convert PR scores and node metadata into a tidy DataFrame."""
    return (pd.DataFrame({
        "id": [g.vp["id"][v] for v in g.vertices()],
        "pr_score": [float(pr_scores[v]) for v in g.vertices()],   # <-- use pr_score
        "is_infohazard_related": [bool(g.vp["is_infohazard_related"][v]) for v in g.vertices()],
        "node_type": [str(g.vp["type"][v]) for v in g.vertices()],
    })
    .dropna(subset=["node_type", "pr_score"])
    .reset_index(drop=True))


def agg_by_type(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate PR mass and counts by node_type × IH flag; return shares and counts."""
    required = ["pr_score", "node_type", "is_infohazard_related"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"agg_by_type missing columns: {missing}. Have: {list(df.columns)}")

    # Total PR mass (avoid div-by-zero)
    total = df["pr_score"].sum()
    grp = df.groupby(["node_type", "is_infohazard_related"], dropna=False)

    # Sum mass and normalize to share of total
    out = grp["pr_score"].sum().rename("pr_mass_share").to_frame()
    if total > 0:
        out["pr_mass_share"] = out["pr_mass_share"] / total

    # Count nodes in each group
    out["count"] = grp.size()

    return out.reset_index()

def edge_maps(edges_df: pd.DataFrame):
    """Precompute base weights in both orientations for quick lookup."""
    ed = edges_df.copy()
    ed["source_id"] = ed["source_id"].astype(str).str.strip().str.lower()
    ed["target_id"] = ed["target_id"].astype(str).str.strip().str.lower()
    if "weighting" not in ed.columns:
        ed["weighting"] = 1.0
    ed["weighting"] = ed["weighting"].astype(float)
    fwd = {(r["source_id"], r["target_id"]): r["weighting"] for _, r in ed.iterrows()}
    rev = {(r["target_id"], r["source_id"]): r["weighting"] for _, r in ed.iterrows()}
    return fwd, rev

def make_edge_weights_for_graph(g: Graph, fwd_map, rev_map, variant="BW", lambda_edge=lambda_decay, beta=3.0):
    """Build edge-weight property from fwd/rev maps with optional time-decay/exp variants."""
    e_w = g.new_edge_property("double")
    v_id   = g.vp["id"]
    v_year = g.vp["year"]
    now    = datetime.now().year

    for e in g.edges():
        u, v = e.source(), e.target()
        uid, vid = v_id[u], v_id[v]

        base = fwd_map.get((uid, vid))
        match_forward = True
        if base is None:
            base = rev_map.get((uid, vid), 1.0)
            match_forward = False
        base = float(base)

        if variant == "BW":
            w = base
        else:
            citer_v = u if match_forward else v
            citer_year = int(v_year[citer_v])
            age = max(0, now - citer_year)
            td  = math.exp(-lambda_edge * age)
            if variant == "BW_TD":
                w = base * td
            elif variant == "EXP":
                w = (base * td) ** beta
            else:
                w = base

        # NO epsilon/floor - enforce strictly positive and finite
        if (not np.isfinite(w)) or (w <= 0.0):
            raise ValueError(f"Non-positive or non-finite weight for edge {uid}->{vid}: {w}")
        e_w[e] = float(w)
    return e_w

def normalize_df(df):
    """Normalize column names: 'score'→'pagerank', 'is_infohazard_related'→'is_infohaz'."""
    if "score" in df.columns and "pagerank" not in df.columns:
        df = df.rename(columns={"score": "pagerank"})
    if "is_infohazard_related" in df.columns:
        df = df.rename(columns={"is_infohazard_related": "is_infohaz"})
    return df


#========================================================================
# Build initial graph and run multiplicaive Personalized PageRank (MPPR)
#========================================================================

def run_graph_and_analysis():
    """Contruct grpahs and run main comparative analysis."""

    print("Building initial graph 'g' and running MPPR model")

    # --- Normalize IDs ---
    nodes_df["id"] = nodes_df["id"].apply(normalize_id)
    edges_df["source_id"] = edges_df["source_id"].apply(normalize_id)
    edges_df["target_id"] = edges_df["target_id"].apply(normalize_id)

    fwd_map, rev_map = edge_maps(edges_df) 

    g, e_weight, bias_vector, pr_scores, pr_df, num_iters= build_base_ppr_graph(
    nodes_df,
    edges_df,
    core_dois=core_dois,
    lambda_decay=lambda_decay,
    pr_output_file = os.path.join(results_dir, "MPPR_results.csv")
    )

#----------------------------------------------------------------------------
# Build comparison variant graphs based on initial graph and run analysis
#-----------------------------------------------------------------------------
    print("Building variant graphs...\n")

    summary_internal, variant_scores, pr_baseline = run_all_variants(
        g=g,
        bias_vector=bias_vector,
        e_weight=e_weight,
        pr_scores=pr_scores
    )

    baseline_scores = variant_scores["Baseline"]

    print("Weighted graph, uniform bias vector")
    print("Unweighted graph, uniform bias vector")
    print("Unweighted graph, base PPR bias vector")
    print("Weighted graph, random bias vector")
    print("Weighted graph, bias vector restricted to layer scores")
    print("Weighted graph, bias vector restricted to time decay")
    print("Weighted graph, linear combination of layer and time decay vectors, tested with mix_weight (mw) ∈ {0.25, 0.5, 0.75}")
    print("Weighted graph, bias vector restricted to node type")

#----------------------------------------------------------------------------
# Build graph with opposite edge direction and run analysis
#----------------------------------------------------------------------------
    print("\nBuilding variant graph: Rev+MBV...\n")

    pr_dir, metrics_directional, g_dir = compare_directional_graph(
        edges_df=edges_df,
        nodes_df=nodes_df,
        core_dois=core_dois,
        pr_scores=baseline_scores,  
        label="Rev+MBV"
    )

    print("Reversed edge direction graph built and MPPR run\n")

#----------------------------------------------------------------------------
# Build an undirected and unweighted graph and run Pagerank for comparison
#----------------------------------------------------------------------------

    print("Building variant graph: UUW+UBV...\n")

    # Structural baseline vs baseline
    pr_struct, metrics_structural = analyze_structural_baseline(
        g=g,
        reference_scores=baseline_scores,
        label="UUW+UBV",
        alpha=DAMPING
    )

    print("Undirected and unweighted graph built, run with uniform bias vector\n")
    
#----------------------------------------------------------------------------
# Build summary table of metrics comparing variants to baseline (UNW + uniform BV)
#----------------------------------------------------------------------------

    # Keep UUW+UBV in the pooled variants (grid)
    if not isinstance(pr_struct, pd.DataFrame):
        variant_scores["UUW+UBV"] = df_from_scores(g, pr_struct)
    else:
        variant_scores["UUW+UBV"] = pr_struct

    # Keep Rev+MBV separate (do NOT add to variant_scores)
    pr_rev_df = pr_dir.copy() if isinstance(pr_dir, pd.DataFrame) else df_from_scores(g_dir, pr_dir)
    variant_scores.pop("Rev+MBV", None)  # just in case    

    summary_df = pd.concat(
        [
            # pd.DataFrame([main_metrics]),
            summary_internal,   
            pd.DataFrame([metrics_directional]),
            pd.DataFrame([metrics_structural]),
        ],
        ignore_index=True
    )

    # print("Variant graph result comparison table:\n")

    cols_order = [
        "Variant",
        "Spearman",  
        "Overlap top_100 (%)", "Overlap top_500 (%)", "Overlap top 1pct (%)", "Overlap top 5pct (%)",
        "Top_100 IH_pct (%)", "Top_500 IH_pct (%)", "Top 1pct_IH (%)", "Top 5pct_IH (%)",
        "Δ top 100 (%)", "Average IH percentile rank (AIHPR)", "Δ AIHPR (%)",
        "Mann-Whitney U", "Mann-Whitney P", "Effect size (\delta)", "Effect size 95% CI",
    ]
    summary_df = summary_df.reindex(columns=[c for c in cols_order if c in summary_df.columns])
    variant_output_file = os.path.join(results_dir, "variant_comparison_table.csv")
    summary_df.to_csv(variant_output_file, index=False, encoding="utf-8-sig")
    print(f"Variant comparison table saved to {variant_output_file}")


    print("\nGenerating combined grid plots for all variants\n")

    # variant_names = list(variant_scores.keys())

    variant_names = [n for n in variant_scores.keys() if n != "Rev+MBV"]
    n_variants = len(variant_names)
    ncols = 3
    nrows = int(np.ceil(n_variants / ncols))

    variant_scores_df = {}
    for name in variant_names:
        val = variant_scores[name]
        df = val.copy() if isinstance(val, pd.DataFrame) else df_from_scores(g, val)
        df = normalize_df(df)
        if "is_infohaz" not in df.columns:
            df["is_infohaz"] = False
        variant_scores_df[name] = df

# ---------------- PPR score plots ----------------
    per_variant = {}
    all_ppr = []

    for name in variant_names:
        df_var = variant_scores_df[name] 
        ih  = df_var.loc[df_var["is_infohaz"],  "pagerank"].to_numpy()
        non = df_var.loc[~df_var["is_infohaz"], "pagerank"].to_numpy()
        per_variant[name] = (ih, non)
        if len(ih) and len(non):
            all_ppr.append(ih); all_ppr.append(non)

    if len(all_ppr) == 0:
        print("No PPR data available for plotting.")
    else:
        all_ppr = np.concatenate(all_ppr)
        global_bins = np.histogram_bin_edges(all_ppr, bins=50)
        xmin, xmax = float(np.min(all_ppr)), float(np.max(all_ppr))

        fig, axes = plt.subplots(nrows, ncols, figsize=(6*ncols, 5*nrows), sharey=True)
        axes = axes.flatten()

        for i, (ax, name) in enumerate(zip(axes, variant_names)):
            ih, non = per_variant[name]
            if len(ih) and len(non):
                ax.hist(ih,  bins=global_bins, alpha=0.6, label="IH-related",     density=False)
                ax.hist(non, bins=global_bins, alpha=0.6, label="Non-IH-related", density=False)
                ax.set_xlim(xmin, xmax)
                ax.set_yscale("log")
                ax.set_ylim(0.1, 1e6) 
                ax.set_title(f"{name}: PPR scores", pad=6)

                if i % ncols == 0: 
                    ax.set_ylabel("Number of nodes")
                else:               
                    ax.set_ylabel("")
                
                ax.set_xlabel("PPR score")

        for ax in axes[len(variant_names):]:
            ax.set_visible(False)

        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        out = os.path.join(results_dir, "distribution_plots_ppr_scores_all_variants.png")
        plt.savefig(out, dpi=300, bbox_inches="tight"); plt.close()
        print(f"Saved {out}")

    # ---- Rev+MBV plot ----
    df_rev = pr_rev_df.copy()

    # make sure columns exist for plotting
    if "pagerank" not in df_rev.columns:
        if "score" in df_rev.columns:
            df_rev = df_rev.rename(columns={"score": "pagerank"})
        else:
            num_cols = df_rev.select_dtypes(include=[np.number]).columns
            if len(num_cols):
                df_rev = df_rev.rename(columns={num_cols[0]: "pagerank"})
    if "is_infohaz" not in df_rev.columns:
        df_rev["is_infohaz"] = False

    ih_rev  = df_rev.loc[df_rev["is_infohaz"],  "pagerank"].to_numpy()
    non_rev = df_rev.loc[~df_rev["is_infohaz"], "pagerank"].to_numpy()

    if len(ih_rev) and len(non_rev):
        data = np.concatenate([ih_rev, non_rev])
        bins = np.histogram_bin_edges(data, bins=50)
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.hist(ih_rev,  bins=bins, alpha=0.6, density=False, label="IH-related")
        ax.hist(non_rev, bins=bins, alpha=0.6, density=False, label="Non-IH-related")
        ax.set_yscale("log")
        ax.set_ylim(0.1, 1e6)
        ax.set_title("Rev+MBV: PPR scores", pad=6)
        ax.set_xlabel("PPR score"); ax.set_ylabel("Number of nodes")
        out = os.path.join(results_dir, "distribution_plots_ppr_scores_Rev_MBV.png")
        plt.savefig(out, dpi=300, bbox_inches="tight"); plt.close()
        print(f"Saved {out}")

    # ------------- Rank-percentile plots  -------------
    per_variant = {}
    all_rp = []

    for name in variant_names:
        df_var = variant_scores_df[name].copy()  
        # Ensure percentile_rank exists and is stored on 0–100 scale (0=best, 100=worst)
        if "percentile_rank" not in df_var.columns:
            if "rank" not in df_var.columns:
                if "pagerank" in df_var.columns:
                    df_var["rank"] = df_var["pagerank"].rank(ascending=False, method="average")
                else:
                    variant_scores_df[name] = df_var
                    continue
            N = len(df_var)
            df_var["percentile_rank"] = ((df_var["rank"] - 1) / N) * 100 if N > 1 else 0.0

        # Write back
        variant_scores_df[name] = df_var

        ih  = df_var.loc[df_var["is_infohaz"],  "percentile_rank"].to_numpy() / 100.0
        non = df_var.loc[~df_var["is_infohaz"], "percentile_rank"].to_numpy() / 100.0
        per_variant[name] = (ih, non)

        if len(ih) and len(non):
            all_rp.append(ih); all_rp.append(non)

    if len(all_rp) == 0:
        print("No rank-percentile data available for plotting.")
    else:
        all_rp = np.concatenate(all_rp)
        global_bins = np.linspace(0, 1, 41)

        fig, axes = plt.subplots(nrows, ncols, figsize=(6*ncols, 5*nrows), sharey=True)
        axes = axes.flatten()

        colors = {"IH-related": "C0", "Non-IH-related": "C1"}

        for i, (ax, name) in enumerate(zip(axes, variant_names)):
            ih, non = per_variant[name]
            if len(ih) and len(non):
                # plot histograms
                ax.hist(ih,  bins=global_bins, alpha=0.6, density=True,
                        color=colors["IH-related"], label="IH-related" if i == 0 else "")
                ax.hist(non, bins=global_bins, alpha=0.6, density=True,
                        color=colors["Non-IH-related"], label="Non-IH-related" if i == 0 else "")

                # plot mean lines
                ax.axvline(np.nanmean(ih),  linestyle="--", linewidth=1,
                        color=colors["IH-related"], label="Mean (IH-related)" if i == 0 else "")
                ax.axvline(np.nanmean(non), linestyle=":",  linewidth=1,
                        color=colors["Non-IH-related"], label="Mean (Non-IH-related)" if i == 0 else "")

                ax.set_title(f"{name}: percentile_rank", pad=6)

                # Always put labels
                ax.set_ylabel("Probability density")
                ax.set_xlabel("Rank percentile (0 = top rank, 1 = lowest rank)")
            else:
                ax.set_visible(False)
                
        # remove empty axes
        for ax in axes[len(variant_names):]:
            ax.set_visible(False)

        # only build legend from the first subplot
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(
            handles, labels,
            loc="lower right",
            bbox_to_anchor=(0.98, -0.02),  # x ~ 1 pushes it right, y < 0 pushes below
            frameon=False,
            ncol=2
        )

        # adjust layout so there is room for legend below plots
        fig.tight_layout(rect=[0, 0.05, 1, 0.96])  
        out = os.path.join(results_dir, "distribution_plots_percentile_ranks_all_variants.png")
        plt.savefig(out, dpi=300, bbox_inches="tight"); plt.close()
        print(f"Saved {out}")

#--------------------------------------------------------------------------------------
    # ---- Rev+MBV: plot ----
    df_rev = pr_rev_df.copy()

    # Minimal, local fixes for required cols
    if "pagerank" not in df_rev.columns:
        if "score" in df_rev.columns:
            df_rev = df_rev.rename(columns={"score": "pagerank"})
        else:
            num_cols = df_rev.select_dtypes(include=[np.number]).columns
            if len(num_cols):
                df_rev = df_rev.rename(columns={num_cols[0]: "pagerank"})
    if "is_infohaz" not in df_rev.columns:
        df_rev["is_infohaz"] = False

    # Ensure percentile_rank exists (store 0–100 using YOUR formula)
    if "percentile_rank" not in df_rev.columns:
        if "rank" not in df_rev.columns:
            df_rev["rank"] = df_rev["pagerank"].rank(ascending=False, method="average")
        N = len(df_rev)
        df_rev["percentile_rank"] = ((df_rev["rank"] - 1) / N) * 100 if N > 1 else 0.0

    ih_rev  = (df_rev.loc[df_rev["is_infohaz"],  "percentile_rank"].to_numpy()) / 100.0
    non_rev = (df_rev.loc[~df_rev["is_infohaz"], "percentile_rank"].to_numpy()) / 100.0

    if len(ih_rev) and len(non_rev):
        bins = np.linspace(0, 1, 41)
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.hist(ih_rev,  bins=bins, alpha=0.6, density=True, label="IH-related")
        ax.hist(non_rev, bins=bins, alpha=0.6, density=True, label="Non-IH-related")
        ax.axvline(np.nanmean(ih_rev),  linestyle="--", linewidth=1, label="Mean (IH-related)")
        ax.axvline(np.nanmean(non_rev), linestyle=":",  linewidth=1, label="Mean (Non-IH-related)")
        ax.set_title("Rev+MBV: percentile_rank", pad=6)
        ax.set_xlabel("Rank percentile (0 = top rank, 1 = lowest rank)")
        ax.set_ylabel("Probability density")
        out = os.path.join(results_dir, "distribution_plots_percentile_ranks_Rev_MBV.png")
        plt.savefig(out, dpi=300, bbox_inches="tight"); plt.close()
        print(f"Saved {out}")
    #-------------------------------------------------------------------------------------------------------

    return g, pr_scores, bias_vector, e_weight, g_dir, fwd_map, rev_map


# ======================================================================================================
# PPR experiments on base graph 'g' to detemine impacts of edge weight and bias vector tweaks
# ======================================================================================================
def run_experiments(g, pr_scores, bias_vector, e_weight, g_dir, fwd_map, rev_map):
    """Run experiments 1-3."""

    print("Running experiments and analysis\n")

#----------------------------------
# Edge weight experiments
#----------------------------------

    print("1/3. Running edge weight variation experiment...\n")

#--------------------------------------------------------------------
# Experiment 1a, fixed base comparison with same bv vector by alpha
#--------------------------------------------------------------------

    print ("\nExperiment 1a - fixed base (UNW) comparison with same bv vector by alpha")    

    bv_layer_time = build_bv_layer_time(g, lambda_node=lambda_decay) 

    RESULTS_A = os.path.join(results_dir, "Exp_1a_weights_vs_UNW_by_alpha.csv")
    rows = []

    for alpha in ALPHAS:
        # Build edge-weight variants at this alpha
        variants = {
            "UNW":        make_edge_weights(g, "UNW"),
            "BW":         make_edge_weights(g, "BW"),
            "BW_D":      make_edge_weights(g, "BW_D", lambda_edge=lambda_decay),
            "BW_D_L":    make_edge_weights(g, "BW_D", lambda_edge=lambda_decay, use_layer=True),
            "BW_D_L_T":   make_edge_weights(g, "BW_D", lambda_edge=lambda_decay, use_layer=True, use_type=True),
        }
        for b in BETAS:
            variants[f"EXP_D_b{b:g}"]    = make_edge_weights(g, "EXP", lambda_edge=lambda_decay, beta=b)
            variants[f"EXP_D_L_b{b:g}"]  = make_edge_weights(g, "EXP", lambda_edge=lambda_decay, beta=b, use_layer=True)
            variants[f"EXP_D_L_T_b{b:g}"] = make_edge_weights(g, "EXP", lambda_edge=lambda_decay, beta=b, use_layer=True, use_type=True)

        # Run PPR for all variants at this alpha
        scores = {name: run_ppr(g, alpha, eprop, bv_layer_time) for name, eprop in variants.items()}

        # Baseline: UNW at the same alpha
        base = scores["UNW"]

        for name, sc in scores.items():
            if name.startswith("EXP"):
                family = name.split("_b", 1)[0]  # EXP / EXP_L / EXP_LT
                try:
                    beta_val = float(name.split("_b", 1)[1])
                except Exception:
                    beta_val = None
                variant_label = family
            else:
                beta_val = None
                variant_label = name

            res = summarize_variant(name, sc, base, g) 
            res.update({"Alpha": alpha, "Variant": variant_label, "Beta": beta_val})
            rows.append(res)

    dfA = pd.DataFrame(rows)
    dfA = dfA[[
        "Alpha","Variant","Beta","Spearman",
        "Overlap top_100 (%)","Overlap top_500 (%)","Overlap top 1pct (%)","Overlap top 5pct (%)",
        "Top_100 IH_pct (%)","Top_500 IH_pct (%)","Top 1pct_IH (%)","Top 5pct_IH (%)",
        "Δ top 100 (%)","Average IH percentile rank (AIHPR)","Δ AIHPR (%)"
    ]]

    os.makedirs(os.path.dirname(RESULTS_A), exist_ok=True)
    dfA.to_csv(RESULTS_A, index=False, encoding="utf-8-sig", float_format="%.9f")
    print(f"Experiment 1a saved to {RESULTS_A}")

#------------------------------------------------
# Experiment 1b - alpha value sensitivity
#------------------------------------------------

    print ("\nExperiment 1b - alpha value sensitivity")
    ALPHA_BASE = DAMPING 
    bv_layer_time = build_bv_layer_time(g, lambda_node=lambda_decay)

    RESULTS_B = os.path.join(results_dir, "Exp_1b_alpha_sensitivity_by_variant.csv")

    # Define all variants once
    variants_all = {
        "UNW":        make_edge_weights(g, "UNW"),
        "BW":         make_edge_weights(g, "BW"),
        "BW_D":      make_edge_weights(g, "BW_D", lambda_edge=lambda_decay),
        "BW_D_L":    make_edge_weights(g, "BW_D", lambda_edge=lambda_decay, use_layer=True),
        "BW_D_L_T":   make_edge_weights(g, "BW_D", lambda_edge=lambda_decay, use_layer=True, use_type=True),
    }
    for b in BETAS:
        variants_all[f"EXP_D_b{b:g}"]    = make_edge_weights(g, "EXP", lambda_edge=lambda_decay, beta=b)
        variants_all[f"EXP_D_L_b{b:g}"]  = make_edge_weights(g, "EXP", lambda_edge=lambda_decay, beta=b, use_layer=True)
        variants_all[f"EXP_D_L_T_b{b:g}"] = make_edge_weights(g, "EXP", lambda_edge=lambda_decay, beta=b, use_layer=True, use_type=True)

    # Baselines: each variant at α_base
    scores_base = {name: run_ppr(g, ALPHA_BASE, eprop, bv_layer_time) for name, eprop in variants_all.items()}

    rows = []
    for alpha in ALPHAS:
        scores_alpha = {name: run_ppr(g, alpha, eprop, bv_layer_time) for name, eprop in variants_all.items()}

        for name, sc in scores_alpha.items():
            if name.startswith("EXP"):
                family = name.split("_b", 1)[0]
                try:
                    beta_val = float(name.split("_b", 1)[1])
                except Exception:
                    beta_val = None
                variant_label = family
            else:
                beta_val = None
                variant_label = name

            res = summarize_variant(f"{name} (α={alpha})", sc, scores_base[name], g)
            res.update({
                "Alpha": alpha,
                "Alpha base": ALPHA_BASE,
                "Variant": variant_label,
                "Beta": beta_val,
                "VS": f"{variant_label} @ α={ALPHA_BASE}",
            })
            rows.append(res)

    dfB = pd.DataFrame(rows)
    dfB = dfB[[
        "Alpha","Alpha base","Variant","Beta", "VS","Spearman",
        "Overlap top_100 (%)","Overlap top_500 (%)","Overlap top 1pct (%)","Overlap top 5pct (%)",
        "Top_100 IH_pct (%)","Top_500 IH_pct (%)","Top 1pct_IH (%)","Top 5pct_IH (%)",
        "Δ top 100 (%)","Average IH percentile rank (AIHPR)","Δ AIHPR (%)"
    ]]

    os.makedirs(os.path.dirname(RESULTS_B), exist_ok=True)
    dfB.to_csv(RESULTS_B, index=False, encoding="utf-8-sig", float_format="%.9f")
    print(f"Experiment 1b saved to {RESULTS_B}")

# ======================================================================================================
# Information hazard related sources analysis
# ======================================================================================================

#------------------------------------------------
# IH related enrichment in top ranked sources
#------------------------------------------------

    print("\n2/3. Running infohazard (IH)-related nodes analysis (a-c)...\n")
    print("2a. IH enrichment in groups of top nodes\n")

    # 1) Baseline = MPPR 
    pr_main = pr_scores 

    # 2) Build alternative bias vectors
    bv_uniform = build_uniform_bias_vector(g)
    bv_random  = build_random_bias_vector(g)
    bv_layer   = build_bv_layer_only(g)
    bv_time    = build_bv_time_only(g, lambda_node=lambda_decay)
    bv_type    = build_bv_type_only(g) 

    pr_layer  = run_pagerank(g, weight=e_weight, pers=bv_layer)
    pr_time   = run_pagerank(g, weight=e_weight, pers=bv_time)
    pr_mwv_025 = mwv(g, pr_layer, pr_time, mix_weight=0.25)
    pr_mwv_050 = mwv(g, pr_layer, pr_time, mix_weight=0.5)
    pr_mwv_075 = mwv(g, pr_layer, pr_time, mix_weight=0.75)

    # 3) Assemble variants list (mix of BV-based and PR-based)
    variants = [
        {"label": "W+UBV", "bv": bv_uniform, "weighted": True},
        {"label": "W+RBV", "bv": bv_random, "weighted": True},
        {"label": "W+LBV", "bv": bv_layer, "weighted": True},
        {"label": "W+DBV", "bv": bv_time, "weighted": True},
        {"label": "W+MWBV_0.25", "pr": pr_mwv_025},
        {"label": "W+MWBV_0.5", "pr": pr_mwv_050},
        {"label": "W+MWBV_0.75", "pr": pr_mwv_075},
        {"label": "W+TBV", "bv": bv_type, "weighted": True},
    ]

    # 4) Run the compact enrichment table vs MPPR
    df_enrich_comparison = run_ih_enrichment_vs_mppr(
        g=g,
        pr_main=pr_main,
        alpha=DAMPING,
        variants=variants,
        results_dir=results_dir,
        outfile="Exp_2a_ih_enrichment_vs_MPPR.csv",
    )

#---------------------------------------------------------------------------------------------
# PR mass share gains and losses per node type and by class (IH vs non-IH related nodes)
#---------------------------------------------------------------------------------------------
    print("\n2b. PR mass share gains and losses per node type and by class (IH vs non-IH) "
        "for MAIN PPR vs UNW + uniform BV\n")

    # Uniform BV
    try:
        bv_uniform
    except NameError:
        try:
            bv_uniform = build_uniform_bias_vector(g)
        except NameError:
            bv_uniform = g.new_vertex_property("double")
            n = max(1, g.num_vertices())
            val = 1.0 / n
            for v in g.vertices():
                bv_uniform[v] = val

    # MPPR BV: layer × time 
    try:
        bv_layer_time
    except NameError:
        try:
            bv_layer_time = build_bv_layer_time(g, lambda_node=lambda_decay)
        except NameError:
            bv_layer_time = bias_vector

    # Baseline: UNW + uniform BV 
    pr_baseline = run_pagerank(g, weight=None, pers=bv_uniform)
    df_base = pr_to_df(g, pr_baseline)    
    tbl_base = agg_by_type(df_base)         

    # MPPR
    pr_mppr = run_pagerank(g, weight=g.ep["weight"], pers=bv_layer_time)
    df_mppr = pr_to_df(g, pr_mppr)
    tbl_mppr = agg_by_type(df_mppr)

    # Merge and compare 
    cmp_base_mppr = (
        tbl_base.merge(
            tbl_mppr,
            on=["node_type", "is_infohazard_related"],
            suffixes=("_baseline", "_mppr"),
            how="outer",
        )
        .fillna(0.0)
    )

    # Keep only one count column (baseline), drop the mppr one
    if "count_mppr" in cmp_base_mppr.columns:
        cmp_base_mppr.drop(columns=["count_mppr"], inplace=True)
    cmp_base_mppr.rename(columns={"count_baseline": "count"}, inplace=True)

    # Compute absolute and relative changes using the share columns
    cmp_base_mppr["delta_pr_mass_share"] = (
        cmp_base_mppr["pr_mass_share_mppr"] - cmp_base_mppr["pr_mass_share_baseline"]
    ).round(6)

    cmp_base_mppr["rel_change_mass_%"] = np.where(
        cmp_base_mppr["pr_mass_share_baseline"] > 0,
        100.0 * (cmp_base_mppr["pr_mass_share_mppr"] / cmp_base_mppr["pr_mass_share_baseline"] - 1.0),
        np.nan
    ).round(2)

    # Sort and save
    cmp_sorted = (
        cmp_base_mppr
        .sort_values("delta_pr_mass_share", ascending=False)
        .reset_index(drop=True)
    )

    cmp_output_file = os.path.join(results_dir, "Exp_2b_MPPR_vs_UNW_pr_mass_share.csv")
    cmp_sorted.to_csv(cmp_output_file, index=False, encoding="utf-8-sig")
    print(f"Saved full PR mass share comparison to {cmp_output_file}")

    #---------------------------------------------------------------------------------------------------------------------------------------
    # 3. Compute seaparate correlations between pagerank scores and assigned base weights, layer scores, and time decay
    #---------------------------------------------------------------------------------------------------------------------------------------

    print("\n3/3. Running analysis of correlations between PPR scores and assigned base node weights, layer scores, and time decay...\n")

    # ------------------------------------------------
    # Build DataFrame with PageRank deltas
    # ------------------------------------------------

    now_year = datetime.now().year  

    if "layer_score" in g.vp:
        del g.vp["layer_score"]
        ensure_layer_score(g, core_dois) 

    layer_scores = [float(g.vp["layer_score"][v]) for v in g.vertices()]

    time_decays = [np.exp(-lambda_decay * max(0, now_year - g.vp["year"][v]))
                for v in g.vertices()]

    # Run two PPR models
    bv_uniform = build_uniform_bias_vector(g)
    pr_baseline = pagerank(g, damping=DAMPING, weight=None, pers=bv_uniform)
    pr_model    = pagerank(g, damping=DAMPING, weight=g.ep["weight"], pers=bias_vector)

    # Build DataFrame
    df = pd.DataFrame({
        "id": [g.vp["id"][v] for v in g.vertices()],
        "is_ih": [bool(g.vp["is_infohazard_related"][v]) for v in g.vertices()],
        "pr_baseline": [float(pr_baseline[v]) for v in g.vertices()],
        "pr_model": [float(pr_model[v]) for v in g.vertices()],
        "layer_score": layer_scores,
        "time_decay": time_decays,
        "base_weight_mean": [
            np.mean([g.ep["weight"][e] for e in v.out_edges()]) if v.out_degree() > 0 else 0.0
            for v in g.vertices()
        ]
    })

    # Add ranks and percentiles for each PR variant
    N = len(df)
    for col in ["pr_baseline", "pr_model"]:
        rank_col = f"rank_{col}"
        pct_col  = f"rankpct_{col}"

        ranks = df[col].rank(ascending=False, method="average")
        if N > 1:
            df[rank_col] = ranks
            df[pct_col]  = ((ranks - 1) / N) * 100

    # Add delta PR (MPPR – baseline) for correlation experiments
    df["delta_pr"] = df["pr_model"] - df["pr_baseline"]
    df_ih = df[df["is_ih"]]

    # ------------------------------------------------
    # Correlations + plots 
    # ------------------------------------------------

    # Scatter plots: 3 features vs ΔPageRank scores (MPPR – baseline)

    if "delta_pr" in df_ih.columns:
        y = df_ih["delta_pr"].to_numpy()
    else:
        y = (df_ih["pr_model"] - df_ih["pr_baseline"]).to_numpy()

    features = ["base_weight_mean", "time_decay", "layer_score"]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)

    for ax, feature in zip(axes, features):
        x = df_ih[feature].to_numpy()
        
        # Plot
        ax.scatter(x, y, s=8, alpha=0.6)
        ax.set_xlabel(feature)
        ax.set_title(f"{feature} vs Δ PageRank scores")

    axes[0].set_ylabel("ΔPR score raw (MPPR – baseline (UNW+UBV))")
    fig.suptitle("Scatter plots: features vs Δ PageRank (MPPR – baseline) on IH-related nodes", fontsize=14)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    scatter_file = os.path.join(results_dir, "Exp_3_MPPR_vs_baseline_features_delta_pr_scatter.png")
    plt.savefig(scatter_file, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved combined scatter plot to {scatter_file}")

    # Calculate correlation coefficients (spearman and pearson's r)
    corr_rows = []
    print("\n Feature correlations with Δ PageRank scores (MPPR – baseline) on IH-related nodes:\n")

    for feature in features:
        x = df_ih[feature].to_numpy()
        mask = np.isfinite(x) & np.isfinite(y)

        # Pearson (linear association)
        r_p, p_p = pearsonr(x[mask], y[mask])
        # Spearman (rank/monotonic association)
        r_s, p_s = spearmanr(x[mask], y[mask])

        corr_rows.append({
            "Feature": feature,
            "Pearson's r": round(r_p, 2),
            "Pearson's r P value": p_p,
            "Spearman": round(r_s, 2),
            "Spearman P value": p_s,
            "Number of Nodes": int(mask.sum())
        })

    # Save to CSV
    corr_df = pd.DataFrame(corr_rows)
    corr_df["Pearson's r P value"] = corr_df["Pearson's r P value"].map(lambda x: f"{x:.3e}")
    corr_df["Spearman P value"] = corr_df["Spearman P value"].map(lambda x: f"{x:.3e}")
    corr_file = os.path.join(results_dir, "Exp_3_MPPR_vs_baseline_features_delta_pr_correlations.csv")
    corr_df.to_csv(corr_file, index=False)
    print(f"\nSaved correlations to {corr_file}")

if __name__ == "__main__":
    g, pr_scores, bias_vector, e_weight, g_dir, fwd_map, rev_map = run_graph_and_analysis()
    run_experiments(g, pr_scores, bias_vector, e_weight, g_dir, fwd_map, rev_map)


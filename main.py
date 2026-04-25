import argparse

from run_data_collection import run_data_collection
from run_data_processing import run_data_processing


from collect_altmetric import (
    collect_altmetric_first_order,
    collect_altmetric_second_order_oa_first_order,
    collect_altmetric_second_order_ov_first_order,
)

from collect_openalex import (
    collect_openalex_first_order,
    collect_openalex_second_order,
    collect_openalex_second_order_ov_first_order,
)

from collect_overton import (
    collect_overton_first_order,
    collect_overton_second_order,
    collect_overton_second_order_oa_first_order,
    collect_overton_second_order_alt_first_order,
)

from data_cleaning import clean_data
from create_edges_and_nodes import create_edges, create_nodes
from run_graph_and_analysis import run_graph_and_analysis, run_experiments



def run_data_collection_only():
    print("Running data collection pipeline...\n")

    print("Step 1: OpenAlex first-order")
    collect_openalex_first_order()

    print("\nStep 2: Altmetric first-order")
    collect_altmetric_first_order()

    print("\nStep 3: Overton first-order")
    collect_overton_first_order()

    print("\nStep 4: Overton second-order")
    collect_overton_second_order()

    print("\nStep 5: OpenAlex second-order")
    collect_openalex_second_order()

    print("\nStep 6: Altmetric second-order for OpenAlex first-order")
    collect_altmetric_second_order_oa_first_order()

    print("\nStep 7: Overton second-order for OpenAlex first-order")
    collect_overton_second_order_oa_first_order()

    print("\nStep 8: Overton second-order for Altmetric first-order")
    collect_overton_second_order_alt_first_order()

    print("\nStep 9: Altmetric second-order for Overton first-order")
    collect_altmetric_second_order_ov_first_order()

    print("\nStep 10: OpenAlex second-order for Overton first-order")
    collect_openalex_second_order_ov_first_order()


def run_data_processing_only():
    print("Running data processing pipeline...\n")

    print("Step 1: data cleaning")
    clean_data()

    print("Step 2: ")
    print("creating edges file")
    create_edges()
    print("creating nodes file")
    create_nodes()


def run_graph_and_experiments_only():
    print("Building graph, running experiments and analysis...\n")
    g, pr_scores, tp_vector, e_weight, g_dir, fwd_map, rev_map = run_graph_and_analysis()
    run_experiments(g, pr_scores, tp_vector, e_weight, g_dir, fwd_map, rev_map)
    print("Experiments and analysis complete.")


def main():
    parser = argparse.ArgumentParser(description="Run data collection or individual steps.")
    parser.add_argument(
        "--run",
        type=str,
        default="all",
        help=(
            "Options:\n"
            "  all\n"
            "  data_collection\n"
            "  data_processing\n"
            "  edges_and_nodes\n"
            "  altmetric_first_order\n"
            "  altmetric_second_order_oa_first_order\n"
            "  altmetric_second_order_ov_first_order\n"
            "  openalex_first_order\n"
            "  openalex_second_order\n"
            "  openalex_second_order_ov_first_order\n"
            "  overton_first_order\n"
            "  overton_second_order\n"
            "  overton_second_order_oa_first_order\n"
            "  overton_second_order_alt_first_order\n"
            "  clean_data\n"
            "  edges\n"
            "  nodes\n"
            "  graph_analysis_experiments\n"
        ),
    )
    args = parser.parse_args()
    run = args.run.strip().lower()

    if run == "all":
        print("Running full pipeline (data collection, cleaning, processing, graph creation, experiments, analysis)...")
        run_data_collection()
        run_data_processing()
        g, pr_scores, tp_vector, e_weight, g_dir, fwd_map, rev_map = run_graph_and_analysis()
        run_experiments(g, pr_scores, tp_vector, e_weight, g_dir, fwd_map, rev_map)
        print("Experiments and analysis complete.")

    elif run == "data_collection":
        run_data_collection_only()

    elif run == "data_processing":
        run_data_processing_only()

    elif run == "edges_and_nodes":
        print("creating edges file")
        create_edges()
        print("creating nodes file")
        create_nodes()

    elif run == "graph_analysis_experiments":
        run_graph_and_experiments_only()



    #--------Data collection--------
    # --- Altmetric---
    elif run == "altmetric_first_order":
        print("Running Altmetric first-order extraction...")
        collect_altmetric_first_order()
    elif run == "altmetric_second_order_oa_first_order":
        print("Running Altmetric second-order extraction for OpenAlex first-order sources...")
        collect_altmetric_second_order_oa_first_order()
    elif run == "altmetric_second_order_ov_first_order":
        print("Running Altmetric second-order extraction for Overton first-order sources...")
        collect_altmetric_second_order_ov_first_order()

    # --- OpenAlex ---
    elif run == "openalex_first_order":
        print("Running OpenAlex first-order extraction...")
        collect_openalex_first_order()
    elif run == "openalex_second_order":
        print("Running OpenAlex second-order extraction...")
        collect_openalex_second_order()
    elif run == "openalex_second_order_ov_first_order":
        print("Running OpenAlex second-order extraction for Overton first-order sources...")
        collect_openalex_second_order_ov_first_order()

    # --- Overton ---
    elif run == "overton_first_order":
        print("Running Overton first-order extraction...")
        collect_overton_first_order()
    elif run == "overton_second_order":
        print("Running Overton second-order extraction...")
        collect_overton_second_order()
    elif run == "overton_second_order_oa_first_order":
        print("Running Overton second-order extraction from OpenAlex first-order sources...")
        collect_overton_second_order_oa_first_order()
    elif run == "overton_second_order_alt_first_order":
        print("Running Overton second-order extraction from Altmetric first-order sources...")
        collect_overton_second_order_alt_first_order()


    #--------Data processing--------
    elif run == "clean_data":
        print("Running data cleaning")
        clean_data()
    elif run == "edges":
        print("creating edges file")
        create_edges()
    elif run == "nodes":
        print("creating nodes file")
        create_nodes()

    else:
        print(f"Unknown option '{run}'. Use '--run all', or a valid step name, e.g. '--run data_collection'.")


if __name__ == "__main__":
    main()
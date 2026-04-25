from data_cleaning import clean_data
from create_edges_and_nodes import create_edges, create_nodes

def run_data_processing():
    print("Running data processing pipeline...\n")

    print("Step 1: data cleaning")
    clean_data()

    print("Step 2: ")
    print("creating edges file")
    create_edges()
    print("creating nodes file")
    create_nodes()



if __name__ == "__main__":
    run_data_processing()
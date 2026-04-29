SN: 24040933
INST0062 24/25

# README - Dissertation data pipeline: Multiplicative Personalized PageRank (MPPR)


**The thesis can be found in the file _INST0062_24040933.pdf_**

This file provides instructions to run a modular pipeline for:
(1) collecting citation data from multiple database sources (OpenAlex, Altmetric.com, and Overton APIs),
(2) processing this data to create edges and nodes files, and
(3) constructing citation network graphs to run Multiplicative Personalized PageRank (MPPR), and to run analysis and experiments using these graphs.

The pipeline supports running the entire workflow or specific components (e.g., data collection, data processing, graph creation, analysis and experiments).


## Folder structure

├── raw_data_collection (folder)

├── processed_data (folder)

├── results (folder)

├── main.py

├── init.py

├── run_data_collection.py

├── run_data_processing.py

├── run_graph_and_analysis.py

├── collect_altmetric.py

├── collect_openalex.py

├── collect_overton.py

├── data_cleaning.py

├── create_edges_and_nodes.py

├── utils.py

├── readme.txt

├── requirements.txt


## Dependencies Installation 


1. To install dependencies needed to run the pipeline, navigate to the directory of the 
   24040933_INST0062_supplementary_files folder. In your command shell of choice run:

        pip install -r requirements.txt

2. Graph-tool, the package used to create graphs and run analysis and experiments, can only be run on a Mac or Linux operating system and can't be pip installed.
   To operate it from a Windows system, the easiest way is to install Windows Subsystem for Linux (WSL) - https://learn.microsoft.com/en-us/windows/wsl/install. 
   Further instructions on graph-tool installation can be found here - https://graph-tool.skewed.de/installation.html#windows.
   Once WSL and required packages are installed, enter the below into the bash shell to install the graph-tool package:

        sudo apt-get install python3-graph-tool


## -----------------PIPELINE-----------------


The pipeline is centralized in the main.py file, and designed to be run through command lines.

If run step by step, the pipeline for the project must be run in the order set out below. 
In order for commands to run properly, the steps preceding it must have already been run to completion.
Alternatively, the entire pipeline can be run with one command:

    python3 main.py --run all


1. Data collection


(a) Data collection can be run as an entire process, or step-by-step by database and source order.

(b) First-order sources must be collected before any second-order sources, or an error will occur.

(c) Note that the entire data collection process takes **7-8 hours** to complete. This is because there is a lot of
    data collected from each database's API. Rate limiting requirements for querying the API to once per second also substantially slows 
    this process down. Collected data is already in the raw_data_collection folder for reference.

   **IMPORTANT: Running the data collection pipeline will replace the current data in the raw_data_collection folder, as the code downloads raw data into   this folder**
   **To avoid this issue, you can create a new folder and change "source_dir={new_folder_name}" in collect_altmetric.py, collect_openalex.py, and collect_overton.py.**

(d) To query Altmetric and Overton APIs, you will need an API key. For UCL students and staff, accounts for both platforms
    are free. Access to the OpenAlex AI is free, publicly available, and doesn't require a key.
    --> For access to Altmetric's DETAILS API, UCL staff will need to contact library services, as access is not given out by default with UCL accounts.
    --> For access to Overton's API, sign up with your institutional email, and then message the Overton team for access to the API.
        API access isn't default for UCL Overton accounts.
    --> For access to OpenAlex's API, sign up an email account. You will need to use this email account to set the module configuration attribute "pyalex.config.email"
        in the python scripts to make OpenAlex API access more stable.
        
(e) Downloading a new dataset from each database may result in slightly different numbers of nodes and edges, as these
    databases are constantly being updated. 

(f) To run the whole data collection pipeline, run in the bash shell:

        python3 main.py --run data_collection

(g) To run a specific step in the pipeline, use one of the commands listed below:

        python3 main.py --run {insert command here}

                            >>>> Command options <<<<
                                 altmetric_first_order
                                 altmetric_second_order_oa_first_order          # oa = OpenAlex. Collects Altmetric second-order data from OpenAlex first-
                                                                                       order sources.
                                 altmetric_second_order_ov_first_order          # ov = Overton

                                openalex_first_order
                                openalex_second_order                           # Collects OpenAlex second-order data from OpenAlex first-order sources.
                                openalex_second_order_ov_first_order

                                overton_first_order
                                overton_second_order                            # Collects Overton second-order data from Overton first-order sources.
                                overton_second_order_oa_first_order
                                overton_second_order_alt_first_order            # alt = Altmetric



2. Data processing


(a) Data processing can be run as an entire process, or in two steps by data cleaning and/or edges and node creation.

(b) Data cleaning must be run before edge and node creation, otherwise the required files won't be created.

(c) Data cleaning takes raw_collection_data files (input_directory) and processes files into the processed_data folder (output_directory). Note that running this overwrites files in the processed_data folder.

(d) Create edges and nodes overwrites files in the processed_data folder. If running edges and nodes creation separately, the edges file
    must be created first.

(f) To run the whole data processing pipeline, run in the bash shell:

        python3 main.py --run data_processing

(g) To run a specific step in the pipeline, use one of the commands listed below:

        python3 main.py --run {insert command here}

                            >>>> Command options <<<<
                                 clean_data                  # run data cleaning only
                                 edges_and_nodes             # create edges and nodes together
                                 edges                       # create edges only
                                 nodes                       # create nodes only



3. Graph creation, analysis and experiments


(a) Graph creation and analysis is run as an entire process, not in separate steps.

(b) Data collection and data processing must be completed before graph creation and analysis is run.

(c) Graph creation and analysis takes processed_data files (input_directory) and outputs analysis and experiment results in the results folder.

(f) To run the graph creation and analysis pipeline, run in the bash shell:

        python3 main.py --run graph_analysis_experiments


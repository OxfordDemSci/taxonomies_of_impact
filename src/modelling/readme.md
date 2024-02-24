Example for the sys.argvs -- To run the topic model, use something like: 

> python src\topic_modelling.py data/raw/raw_ref_ics_data.xlsx" data/topic_modelled/ Clean_Run Clean_Frequencies

To run to reducer code:

>  python .\src\topic_reduce.py ".\data\topic_modelled\" "nn3" ".\data\topic_modelled\output\nn3.xlsx"
# BC results

v2.1 dev evaluation with seeds 11, 22, and 33.

BC final_model contains the checkpoint already selected by BEST.json using validation loss. Seeds 11, 22, and 33 use updates 20000, 17000, and 18000. Each dev plot shows the single recorded evaluation of that selected checkpoint.

Training graphs are generated from the local run curve.jsonl records used with the JAEKIMSUNG branch. The runs directory is excluded from Git tracking on that branch. Model bundles and dev summaries are copied from those local runs.

Each final_model bundle retains its original SHA256.json and all files covered by that manifest. Load it with kcity.policy.checkpoint.load_policy.

# RLPD results

v2.1 dev evaluation with seeds 11, 22, and 33.

RLPD final_model contains the budget-end checkpoint at 300000 environment transitions. Dev plots show evaluations recorded during training.

Training graphs are generated from the local run curve.jsonl records used with the JAEKIMSUNG branch. The runs directory is excluded from Git tracking on that branch. Model bundles and dev summaries are copied from those local runs.

Each final_model bundle retains its original SHA256.json and all files covered by that manifest. Load it with kcity.policy.checkpoint.load_policy.

from pathlib import Path
import json,sys
from agents import ModelSettings
from netagents.codex_cli_model import CodexCLIModel
from netagents.designs import DESIGNS
from netagents.evaluate import run_one
from netagents.testset import Case
root=Path(__file__).resolve().parent / 'development-smoke'
root.mkdir(exist_ok=False)
case=Case('dag/dev-g4/n1','dag/fixed',[0], opt={'agents':1,'width':2,'depth':1,'grain':4},lockstep=True,calls=30)
row=run_one(DESIGNS['peers'],case,0,CodexCLIModel(root/'transport','gpt-6.1-sol','high'),ModelSettings(tool_choice='required',parallel_tool_calls=False),30,trace=str(root/'trace.jsonl.gz'))
(root/'result.json').write_text(json.dumps(row,indent=2)+'\n')
assert row['solved'] and row['done']==3 and row['llm_errors']==0,row
print(json.dumps({k:row[k] for k in ['solved','done','tasks','steps','lower_bound','llm_tool_calls','llm_errors']}),flush=True)

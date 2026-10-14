from pathlib import Path
import ast,hashlib,json,sys
parent=Path(sys.argv[1]);sys.path.insert(0,str(parent))
import nexus_composite_strategy_research as r
assert (len(r.FACTORY_SPECS),len(r.ALL_MECHANISMS))==(93,120)
source=(parent/"nexus_composite_strategy_research.py").read_text(encoding="utf-8")
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=="backtest")
value={"parent_source_sha":"2b89f6e89abdacc16b3288b9fd9ebcb3bdea7e69",
 "all_mechanisms":list(r.ALL_MECHANISMS),"factory_specs":r.FACTORY_SPECS,
 "frontier_configs":list(r.FRONTIER_CONFIGS),
 "backtest_function_sha256":hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest(),
 "factory_ids":[m for m in r.ALL_MECHANISMS if m in r.FACTORY_SPECS]}
sys.stdout.buffer.write((json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8"))

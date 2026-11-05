import ast
import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]

def functions(relative, names, **context):
    source=ast.parse((ROOT/relative).read_text(encoding="utf-8"))
    nodes=[ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0)]
    nodes.extend(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names)
    namespace={"pd":pd,"datetime":datetime,"sys":sys,**context}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),relative,"exec"),namespace)
    return namespace

class MigrationTests(unittest.TestCase):
    def test_missing_company_pledge_does_not_receive_low_risk_points(self):
        frame=pd.DataFrame([{"symbol":"000001.SZ","quarter":"2025q4","bs_total_assets":100,"bs_total_liab":20,"bs_total_cur_assets":50,"bs_total_cur_liab":10}])
        for path in ["scripts/full_scoring.py","scripts/full_scoring_v2.py"]:
            sdk=Mock();sdk.get_stock_pledge_stat.side_effect=ValueError("market-wide statistics")
            ns=functions(path,{"score_debt"},panda_data=sdk,get_fina=lambda sym:frame)
            score,parts=ns["score_debt"]("000001.SZ",frame) if path.endswith("full_scoring.py") else ns["score_debt"]("000001.SZ")
            detail=parts["股权质押"]
            points=detail["得分"] if isinstance(detail,dict) else detail[0]
            self.assertEqual(points,0)
            self.assertIn("未评分",str(detail))
            sdk.get_stock_pledge_stat.assert_not_called()

if __name__ == "__main__":
    unittest.main()

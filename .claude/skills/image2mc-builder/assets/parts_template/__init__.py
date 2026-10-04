"""組み立て役（型のまま。書き換えない）。このフォルダの base.py とパーツ p_*.py を集めて1つの建物にする（スキルの scripts/assemble.py）。"""
from assemble import assemble

assemble(globals(), __name__)

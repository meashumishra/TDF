from tdf.ir import Doc, Para, Table, ListBlock, Heading
from tdf.emit import render_tdf
from tdf.parse import parse_tdf
from tdf.fidelity import compare

# Edge case test 1: Nested / duplicated text and semantic order
doc1 = Doc("Doc1", [Para("Alice reports to Bob.")])
doc2 = Doc("Doc1", [Para("Bob reports to Alice.")])

# TDF Roundtrip for doc1
tdf1 = render_tdf(doc1)
ir1 = parse_tdf(tdf1)

# Fidelity metrics between two different semantic documents with same words
fid = compare(doc1, doc2)
print("Fidelity of doc1 vs doc2 (Semantic Swap):", fid)

# Edge case test 2: Table with shifted numbers
table1 = Table(cols=["Q1", "Q2"], rows=[["10", "20"]])
table2 = Table(cols=["Q1", "Q2"], rows=[["20", "10"]])
fid_table = compare(Doc("T1", [table1]), Doc("T2", [table2]))
print("Fidelity of table1 vs table2 (Swapped columns):", fid_table)

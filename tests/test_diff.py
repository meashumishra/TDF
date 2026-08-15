import pytest
import copy
from pathlib import Path
from tdf.readers import read
from tdf.diff import diff_docs

SAMPLES = Path("samples")

def test_identity():
    doc = read(SAMPLES / "orders.csv")
    diff = diff_docs(doc, doc, summary_only=False)
    # The output should only contain !DIFF and !=
    lines = diff.splitlines()
    assert lines[0].startswith("!DIFF")
    assert all(line.startswith("!=") for line in lines[1:] if line.strip())

def test_mutation():
    doc = read(SAMPLES / "orders.csv")
    new_doc = copy.deepcopy(doc)
    # modify a cell
    new_doc.blocks[0].rows[5][3] = "99999"
    
    diff = diff_docs(doc, new_doc)
    lines = diff.splitlines()
    
    assert any(line.startswith("~") and "99999" in line for line in lines)
    assert not any(line.startswith("!") and line not in ("!DIFF old -> new", "!~ document start  table 500x8  (matched by key: order_id)", "!C\torder_id\tproduct\tregion\torder_date\tamount\tqty\tstatus\tcurrency") for line in lines)

def test_repagination():
    doc = read(SAMPLES / "orders.csv")
    new_doc = copy.deepcopy(doc)
    from tdf.ir import PageMark
    new_doc.blocks.insert(0, PageMark(99))
    
    diff = diff_docs(doc, new_doc)
    # The pagemark should be ignored due to _strip_noise
    lines = diff.splitlines()
    assert lines[0].startswith("!DIFF")
    assert all(line.startswith("!=") for line in lines[1:] if line.strip())

def test_summary_only():
    doc = read(SAMPLES / "orders.csv")
    new_doc = copy.deepcopy(doc)
    new_doc.blocks[0].rows[5][3] = "99999"
    diff = diff_docs(doc, new_doc, summary_only=True)
    
    lines = diff.splitlines()
    assert any(line.startswith("!~") for line in lines)
    # shouldn't contain the actual cell change since it's summary only
    assert not any(line.startswith("~") for line in lines)


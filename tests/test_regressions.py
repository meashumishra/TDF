from tdf.ir import Doc, Table
from tdf.emit import render_tdf
from tdf.parse import parse_tdf

def test_regression_table_cell_quotes():
    """Verify that quote-only table cells and empty strings survive round-trip."""
    table = Table(cols=['""', '"x"', 'a"b', ''], rows=[['""', '"x"', 'a"b', '']], caption='', group='')
    doc = Doc(blocks=[table])
    
    # Test space-separated (forced by len(cols) > 1, though it decides based on length)
    out = render_tdf(doc, optimized=False)
    parsed = parse_tdf(out)
    
    parsed_table = parsed.blocks[0]
    assert parsed_table.cols == ['""', '"x"', 'a"b', '']
    assert parsed_table.rows[0] == ['""', '"x"', 'a"b', '']

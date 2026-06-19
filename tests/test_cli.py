from cli import build_parser


def test_parser_has_ingest_and_query_subcommands():
    parser = build_parser()
    ns = parser.parse_args(["ingest", "--path", "."])
    assert ns.command == "ingest"
    assert ns.path == "."
    assert ns.out == "index"
    assert ns.window == 60
    assert ns.overlap == 15

    ns2 = parser.parse_args(["query", "where is auth?", "-k", "5"])
    assert ns2.command == "query"
    assert ns2.question == "where is auth?"
    assert ns2.k == 5
    assert ns2.index == "index"

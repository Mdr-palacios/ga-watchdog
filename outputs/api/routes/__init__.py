"""Route handlers for the public read API.

Every handler in this package must read from a name in
`_allowed_sources.ALLOWED_PUBLIC_SOURCES`. The
`test_no_route_reads_disallowed_source` test parses each handler's
SQL and enforces this mechanically.
"""

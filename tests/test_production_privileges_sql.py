from __future__ import annotations


def test_internal_public_schema_is_service_role_only(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            select count(*)
            from information_schema.role_table_grants
            where table_schema='public'
              and grantee in ('PUBLIC','anon','authenticated')
            """
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            """
            select count(*)
            from information_schema.routine_privileges
            where specific_schema='public'
              and grantee in ('PUBLIC','anon','authenticated')
            """
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            """
            select count(*)
            from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='public' and c.relkind in ('r','p')
              and not c.relrowsecurity
            """
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "select has_function_privilege('service_role', "
            "'public.commit_graph_turn_v3(text,uuid,bigint,uuid,text,text,text[],bigint,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,text)', "
            "'EXECUTE')"
        )
        assert cur.fetchone()[0] is True

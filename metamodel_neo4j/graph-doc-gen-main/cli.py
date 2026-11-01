import click
from code_parser.extractor import Extractor
from database.neo4j_client import Neo4jClient
from maintenance.repo_utils import resolve_repo_id

@click.group()
def cli():
    """CI/CD-focused Graph Builder CLI."""
    pass

@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--clear/--no-clear', default=False, help='Clear existing Neo4j graph for this repository before parsing.')
@click.option('--repo-id', default=None, help='Explicit repository identifier (e.g. owner/repo).')
def parse(path, clear, repo_id):
    """Parse a directory and upload its skeletal structure to Neo4j with repository isolation."""
    import time
    from maintenance.stats import print_performance_stats
    start = time.time()
    resolved_repo = resolve_repo_id(path, repo_id)
    click.echo(f"Initializing parsing for {path} (repo_id: '{resolved_repo}')...")
    
    extractor = Extractor(repo_id=resolved_repo)
    extractor.parse_directory(path, repo_id=resolved_repo)
    graph = extractor.get_graph()
    click.echo(f"Extracted {len(graph['nodes'])} nodes and {len(graph['edges'])} edges for '{resolved_repo}'.")
    
    client = Neo4jClient()
    try:
        with client.session() as session:
            with session.begin_transaction() as tx:
                client.acquire_repo_lock(resolved_repo, tx)
                if clear:
                    click.echo(f"Clearing repository graph for '{resolved_repo}'...")
                    tx.run("MATCH (n {repo_id: $repo_id}) DETACH DELETE n", repo_id=resolved_repo)
                client.upload_graph(graph['nodes'], graph['edges'], repo_id=resolved_repo, tx=tx)

                # Provenance verification for initial ingestion:
                # Only create verified SyncState if path is a clean Git work tree checked out to a valid commit
                from maintenance.git_utils import is_git_repository, get_head_commit_sha, check_working_tree_clean
                is_git = is_git_repository(path)
                commit_verified = False
                head_sha = None
                if is_git:
                    try:
                        check_working_tree_clean(path)
                        head_sha = get_head_commit_sha(path)
                        commit_verified = True
                        click.echo(f"Verified Git commit provenance for initial ingestion at HEAD: {head_sha}")
                    except Exception as e:
                        click.echo(f"Notice: Working tree not clean or provenance check failed ({e}). Ingestion proceeding without verified commit record.")
                else:
                    click.echo("Notice: Target is not a Git repository. Initial ingestion proceeding without verified commit record.")

                if commit_verified and head_sha:
                    client.record_sync_state(
                        repo_id=resolved_repo,
                        target_sha=head_sha,
                        base_sha=None,
                        status="SYNCED",
                        commit_verified=True,
                        files_parsed=len(set(n["properties"].get("file_path", "") for n in graph["nodes"] if "file_path" in n.get("properties", {}))),
                        files_pruned=0,
                        nodes_count=len(graph['nodes']),
                        edges_count=len(graph['edges']),
                        tx=tx
                    )
                tx.commit()
    finally:
        client.close()

    click.echo("Parsing and upload complete.")
    print_performance_stats(start)

@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--repo-id', default=None, help='Explicit repository identifier.')
@click.option('--base-sha', default=None, help='Base commit SHA for commit-aware diffing.')
@click.option('--target-sha', default=None, help='Target commit SHA for commit-aware diffing.')
def update(path, repo_id, base_sha, target_sha):
    """Incrementally parse changed files and update graph with Continual Graph Learning."""
    import time
    from maintenance.stats import print_performance_stats
    from maintenance.diff_agent import update_graph_from_diff
    start = time.time()
    resolved_repo = resolve_repo_id(path, repo_id)
    click.echo(f"Running incremental update for repo '{resolved_repo}'...")
    res = update_graph_from_diff(path, base_sha=base_sha, target_sha=target_sha, repo_id=resolved_repo)
    click.echo(
        f"Update completed: status={res.get('status')}, "
        f"commit_verified={res.get('commit_verified')}, "
        f"target_sha={res.get('target_sha')}, "
        f"files_parsed={res.get('files_parsed')}, "
        f"files_pruned={res.get('files_pruned')}"
    )
    print_performance_stats(start)

@cli.command()
@click.option('--file', default='architecture.mermaid', help='Output file path.')
@click.option('--fmt', type=click.Choice(['mermaid', 'plantuml', 'drawio']), default='mermaid', help='Diagram format.')
@click.option('--method', type=click.Choice(['static', 'langchain']), default='static', help='Generation method (static query or langchain LLM).')
def export(file, fmt, method):
    """Export graph as diagram (static or via LangChain)."""
    from maintenance.export import export_diagram
    click.echo(f"Exporting {fmt} diagram using {method} method...")
    export_diagram(file, fmt, method)

@cli.command()
@click.option('--force', is_flag=True, default=False, help='Explicitly confirm clearing default or protected database.')
@click.option('--repo-id', default=None, help='Surgically clear only nodes belonging to this repository.')
def clear(force, repo_id):
    """Clear Neo4j graph database, or surgically clear a single repository."""
    client = Neo4jClient()
    try:
        if repo_id and repo_id.strip():
            click.echo(f"Clearing graph data strictly for repository '{repo_id.strip()}'...")
            client.clear_repository(repo_id.strip())
            click.echo(f"Repository '{repo_id.strip()}' cleared successfully.")
        else:
            click.echo("Clearing existing graph database...")
            client.clear_database(force=force)
            click.echo("Database cleared successfully.")
    except Exception as e:
        click.echo(f"Failed to clear: {e}")
    finally:
        client.close()

@cli.command()
@click.argument('repo_id')
@click.argument('file_path')
def investigate(repo_id, file_path):
    """Investigate connected files for a target file within a specific repository."""
    client = Neo4jClient()
    try:
        click.echo(f"Investigating connected files for '{file_path}' in repo '{repo_id}'...")
        connected = client.get_connected_files(repo_id=repo_id, file_path=file_path)
        click.echo(f"Found {len(connected)} connected files:")
        for cf in connected:
            click.echo(f"  - {cf}")
    finally:
        client.close()

@cli.command('migrate-repo-id')
@click.option('--repo-id', default='legacy:default', help='Target repo_id to assign to un-scoped nodes.')
def migrate_cmd(repo_id):
    """Safely migrate unmigrated legacy nodes by setting repo_id without deleting data."""
    from maintenance.migrate_repo_id import migrate_legacy_nodes
    click.echo(f"Running safe legacy migration to repo_id '{repo_id}'...")
    res = migrate_legacy_nodes(default_repo_id=repo_id)
    click.echo(f"Migration completed: {res}")

if __name__ == '__main__':
    cli()
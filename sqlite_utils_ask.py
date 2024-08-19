import click
import json
import re
import sqlite_utils
import textwrap


@sqlite_utils.hookimpl
def register_commands(cli):
    import llm

    @cli.command()
    @click.argument(
        "path",
        type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    )
    @click.argument("question")
    @click.option("model_id", "-m", "--model", help="LLM model to use")
    @click.option("-v", "--verbose", is_flag=True, help="Verbose output")
    def ask(path, question, model_id, verbose):
        "Ask a question of your data"
        db = sqlite_utils.Database(path)
        schema = db.schema
        system = textwrap.dedent(
            """
        You will be given a SQLite schema followed by a question. Generate a single SQL
        query to answer that question. Return that query in a ```sql ... ```
        fenced code block.
                                 
        Example: How many repos are there?
        Answer:
        ```sql
        select count(*) from repos
        ```
        """
        )
        if not model_id:
            model_id = "gpt-4o-mini"
        model = llm.get_model(model_id)
        response = model.prompt(schema + "\n\n" + question, system=system)
        sql = extract_sql_query(response.text())
        if verbose:
            click.echo(sql, err=True)
        if not sql:
            raise click.ClickException(
                "Failed to generate a response:\n\n" + response.text()
            )
        results = list(db.query(sql))
        print(json.dumps({"sql": sql, "results": results}, indent=4, default=repr))


def extract_sql_query(text):
    pattern = r"```sql\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return None

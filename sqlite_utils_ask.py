import click
import json
import re
import sqlite3
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
        # Open in read-only mode
        conn = sqlite3.connect("file:{}?mode=ro".format(str(path)), uri=True)
        db = sqlite_utils.Database(conn)
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
        conversation = model.conversation()
        response = conversation.prompt(schema + "\n\n" + question, system=system)
        if verbose:
            click.echo(response.text(), err=True)
        sql = extract_sql_query(response.text())
        if not sql:
            # Try one more time
            if verbose:
                click.echo(
                    "First attempt did not return SQL:\n" + response.text(), err=True
                )
                click.echo("Trying a second time", err=True)
            response2 = conversation.prompt(
                "Return the SQL query like this:\n```sql\nSELECT ...\n```"
            )
            if verbose:
                click.echo(response2.text(), err=True)
            sql = extract_sql_query(response2.text())
            if not sql:
                raise click.ClickException(
                    "Failed to generate a response:\n\n" + response.text()
                )
        # Try this up to three times
        attempt = 0
        ok = False
        while attempt < 3:
            if verbose:
                if attempt > 0:
                    click.echo(f"Trying again, attempt {attempt + 1}", err=True)
                click.echo(sql, err=True)
            try:
                results = list(db.query(sql))
                ok = True
                break
            except Exception as ex:
                if verbose:
                    click.echo(str(ex), err=True)
                response3 = conversation.prompt(
                    f"Got this error: {str(ex)} - try again"
                )
                if verbose:
                    click.echo(response3.text(), err=True)
                sql = extract_sql_query(response3.text())
            attempt += 1

        if ok:
            click.echo(
                json.dumps({"sql": sql, "results": results}, indent=4, default=repr)
            )
        else:
            click.echo(f"Failed after {attempt} attempts", err=True)
            if verbose:
                click.echo(conversation.responses, err=True)


_pattern = r"```sql\n(.*?)\n```"


def extract_sql_query(text):
    match = re.search(_pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return None

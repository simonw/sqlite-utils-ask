import click
import json
import re
import sqlite3
import sqlite_utils
import textwrap
from typing import Tuple

SYSTEM = """
You will be given a SQLite schema followed by a question. Generate a single SQL
query to answer that question. Return that query in a ```sql ... ```
fenced code block.

Example: How many repos are there?
Answer:
```sql
select count(*) from repos
```
""".strip()


def build_prompt(
    conn: sqlite3.Connection, question: str, examples: bool
) -> Tuple[str, str]:
    db = sqlite_utils.Database(conn)
    schema = db.schema
    prompt = schema + "\n\n"
    if examples:
        # Include 5 examples for each text column that averages < 32 characters
        examples_for_tables = {}
        for table in db.table_names():
            examples_for_tables[table] = get_example_columns(db, table)
        prompt += (
            "Example values:\n\n"
            + json.dumps(examples_for_tables, indent=4, default=repr)
            + "\n\n"
        )
    prompt += question
    return prompt, SYSTEM


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
    @click.option(
        "-e", "--examples", is_flag=True, help="Send example column values to the model"
    )
    @click.option("json_", "-j", "--json", is_flag=True, help="Output as JSON")
    def ask(path, question, model_id, verbose, examples, json_):
        "Ask a question of your data"
        # Open in read-only mode
        conn = sqlite3.connect("file:{}?mode=ro".format(str(path)), uri=True)
        db = sqlite_utils.Database(conn)
        if not model_id:
            model_id = "gpt-4o-mini"
        model = llm.get_model(model_id)
        conversation = model.conversation()
        prompt, system = build_prompt(conn, question, examples)
        if verbose:
            click.echo("System prompt:", err=True)
            click.echo(system, err=True)
            click.echo("Prompt:", err=True)
            click.echo(prompt, err=True)
        response = conversation.prompt(prompt, system=system)
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
                "Return the SQL query like this:\n```sql\nselect ...\n```"
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
            if json_:
                click.echo(
                    json.dumps({"sql": sql, "results": results}, indent=4, default=repr)
                )
            else:
                # Plain text output
                click.echo(sql.strip() + "\n")
                click.echo(json.dumps(results, indent=4, default=repr))
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


def get_example_columns(db, table):
    examples = {}
    try:
        column_types = db[table].columns_dict.items()
    except sqlite3.OperationalError:
        # Probably a vec0 table or similar
        return {}
    for column, type in column_types:
        if type is not str:
            continue
        # Figure out average length
        avg = (
            next(
                db.query(
                    f"""
            select avg(length("{column}")) as a
            from "{table}"
        """
                )
            )["a"]
            or 0
        )
        if avg < 32:
            examples[column] = [
                row["e"]
                for row in db.query(
                    f"""
                    select distinct "{column}" as e from (
                        -- Consider only first 1000 rows
                        select "{column}" from "{table}" limit 1000
                    )
                    where
                        "{column}" is not null
                        and "{column}" != ''
                    limit 5
                """
                )
            ]
    return examples

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from market_research.agent import run_research_agent
from market_research.pdf_renderer import render_pdf
from market_research.utils.config import load_config, validate_config

app = typer.Typer(
    name="market-research",
    help="AI-powered market research agent. Generates professional PDF reports.",
)
console = Console()


@app.command()
def research(
    topic: str = typer.Argument(..., help="The market research topic to investigate"),
    prompt: str = typer.Option(
        "", "--prompt", "-p", help="Additional instructions for the research agent"
    ),
    output_dir: Path = typer.Option(
        Path("./output"), "--output", "-o", help="Directory for the output PDF"
    ),
    max_turns: int = typer.Option(
        50, "--max-turns", "-t", help="Max agent iterations (more = deeper research)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed agent reasoning"
    ),
):
    """Run market research on TOPIC and generate a PDF report."""
    config = load_config()
    validate_config(config)

    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold blue]Researching:[/bold blue] {topic}")
    console.print(f"[dim]Output directory: {output_dir}[/dim]\n")

    def on_progress(message: str, msg_type: str) -> None:
        if msg_type == "search":
            console.print(f"  [yellow]{message}[/yellow]")
        elif msg_type == "fetch":
            console.print(f"  [cyan]{message}[/cyan]")
        elif msg_type == "phase":
            console.print(f"[bold magenta]{message}[/bold magenta]")
        elif verbose:
            console.print(f"[dim]{message}[/dim]")

    try:
        markdown_report = asyncio.run(
            run_research_agent(
                topic=topic,
                additional_instructions=prompt,
                max_turns=max_turns,
                on_progress=on_progress,
            )
        )
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    console.print("[dim]Converting to PDF...[/dim]")

    try:
        pdf_path = render_pdf(
            markdown_content=markdown_report,
            topic=topic,
            output_dir=output_dir,
        )
    except Exception as e:
        md_path = output_dir / f"{topic[:40].replace(' ', '_')}_report.md"
        md_path.write_text(markdown_report, encoding="utf-8")
        console.print(
            f"[bold yellow]PDF generation failed:[/bold yellow] {e}\n"
            f"[dim]Markdown saved to: {md_path}[/dim]"
        )
        raise typer.Exit(code=1)

    console.print(f"\n[bold green]Report saved:[/bold green] {pdf_path}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on"),
):
    """Start the web UI for interactive research."""
    config = load_config()
    validate_config(config)

    console.print(f"[bold blue]Starting Market Research Agent Web UI[/bold blue]")
    console.print(f"[dim]Open http://localhost:{port} in your browser[/dim]\n")

    from market_research.web import start_server

    start_server(host=host, port=port)


if __name__ == "__main__":
    app()

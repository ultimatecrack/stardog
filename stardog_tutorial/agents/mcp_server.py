r"""EduGraph tutor tools as an MCP server (Chapter 17), so any MCP client (Claude Desktop, Claude Code,
IDE agents, …) can use the knowledge graph through the same guarded tools.

Run it over stdio (what MCP clients launch), from the stardog_tutorial folder:
    ..\.venv\Scripts\python agents\mcp_server.py

Settings (environment variables):
    EDUGRAPH_GRAPHS        comma-separated data graphs (default: Chapter 17's graphs)
    EDUGRAPH_MEMORY        prefix of the graphs plans are written to
    EDUGRAPH_SHAPES        graph holding ontology/edugraph_shapes.ttl
    EDUGRAPH_PROVENANCE    graph for provenance records
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mcp.server.mcpserver import MCPServer      # noqa: E402

from kg import client, tutor                    # noqa: E402

PREFIX = 'urn:tutorial:ch17'
DEFAULT_GRAPHS = [f'{PREFIX}:curriculum'] + [f'{PREFIX}:sis:{n}' for n in ('students', 'enrollments', 'assessments')]


def make_server(t: tutor.Tutor) -> MCPServer:
  server = MCPServer('edugraph-tutor', instructions='Tools over the EduGraph knowledge graph: students, topics, '
                     'prerequisites and learning plans. save_plan validates plans against the curriculum before writing.')

  @server.tool()
  def student_profile(student_id: str) -> dict:
    """Profile of a student: name, city, year, courses, number of assessments and average score. Ids look like S023."""
    return t.student_profile(student_id)

  @server.tool()
  def prerequisite_gaps(student_id: str) -> list:
    """Topics a student scored below 50 on that block topics in their courses."""
    return t.prerequisite_gaps(student_id)

  @server.tool()
  def topic_prerequisites(topic_id: str) -> list:
    """All prerequisites of a topic (direct and indirect). Topic ids look like regression, statistics."""
    return t.topic_prerequisites(topic_id)

  @server.tool()
  def previous_plans(student_id: str) -> list:
    """Learning plans saved for a student before."""
    return t.previous_plans(student_id)

  @server.tool()
  def save_plan(student_id: str, target_topic: str, steps: list[str], rationale: str) -> dict:
    """Save a learning plan (topic ids in study order, ending with the target). Rejected plans list the problems to fix."""
    return t.save_plan(student_id, target_topic, steps, rationale)

  return server


if __name__ == '__main__':
  graphs = os.environ.get('EDUGRAPH_GRAPHS', ','.join(DEFAULT_GRAPHS)).split(',')
  t = tutor.Tutor(client.connect(), graphs, os.environ.get('EDUGRAPH_MEMORY', f'{PREFIX}:memory'),
                  os.environ.get('EDUGRAPH_SHAPES', f'{PREFIX}:shapes'),
                  os.environ.get('EDUGRAPH_PROVENANCE', f'{PREFIX}:provenance'), 'mcp-client')
  make_server(t).run()                          # stdio transport

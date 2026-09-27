"""A minimal tool-calling agent loop with a trace (Chapter 17).

    agent = Agent('planner', SYSTEM_PROMPT, tools, cache=CACHE)
    result = agent.run('Make a learning plan for S023 …')
    result['answer'], result['trace']

tools = {name: {'spec': <JSON function spec>, 'fn': callable(**arguments) -> JSON-able}}
"""
import json
from pathlib import Path

from kg import llm


class Agent:
  def __init__(self, name: str, system: str, tools: dict, cache: Path | None = None, max_steps: int = 10):
    self.name, self.system, self.tools, self.cache, self.max_steps = name, system, tools, cache, max_steps

  def run(self, task: str, previous: dict | None = None) -> dict:
    """Let the model call tools until it answers (or max_steps is reached). Every call is traced.

    previous: the result of an earlier run to continue (its conversation and trace are kept), e.g. when
    an orchestrator sends the agent back with "that didn't work, try again".
    """
    if previous:
      messages = previous['messages'] + [{'role': 'user', 'content': task}]
      trace = list(previous['trace'])
    else:
      messages = [{'role': 'system', 'content': self.system}, {'role': 'user', 'content': task}]
      trace = []
    specs = [t['spec'] for t in self.tools.values()]
    for _ in range(self.max_steps):
      reply = llm.chat(messages, tools=specs or None, cache=self.cache)
      messages.append(reply)
      calls = reply.get('tool_calls') or []
      if not calls:
        return {'answer': reply.get('content', ''), 'trace': trace, 'messages': messages}
      for call in calls:
        name, args = call['function']['name'], call['function'].get('arguments') or {}
        if name not in self.tools:
          result = {'error': f'unknown tool {name!r}'}
        else:
          try:
            result = self.tools[name]['fn'](**args)
          except TypeError as e:                          # wrong or missing arguments from the model
            result = {'error': f'bad arguments: {e}'}
        trace.append({'step': len(trace) + 1, 'tool': name, 'arguments': args, 'result': result})
        messages.append({'role': 'tool', 'content': json.dumps(result, default=str)[:4000]})
    return {'answer': '(stopped: too many steps)', 'trace': trace, 'messages': messages}

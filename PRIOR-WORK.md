# Prior work

What is already known about prompt injection against agents, and where Kettle sits.
Every figure below is quoted from the paper or post it is linked to, checked on
2026-11-15. None of them is a Kettle result.

## The problem

- **Indirect prompt injection.** Greshake, Abdelnabi, Mishra, Endres, Holz, Fritz,
  "Not what you've signed up for" (2023). The paper that named the attack Kettle
  tests for: the attacker never talks to the model, they hide text in something
  the agent later reads. https://arxiv.org/abs/2302.12173
- **The lethal trifecta.** Simon Willison (16 June 2025). An agent is exposed when
  it has all three of: private data, content an attacker controls, and a way to
  send things out. https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/

## How it is measured

- **InjecAgent.** Zhan, Liang, Ying, Kang (2024). 1,054 test cases over 17 user
  tools and 62 attacker tools. ReAct-prompted GPT-4 was vulnerable 24% of the
  time. https://arxiv.org/abs/2403.02691
- **AgentDojo.** Debenedetti, Zhang, Balunovic, Beurer-Kellner, Fischer, Tramer
  (2024). 97 realistic tasks and 629 security test cases, in a pretend world,
  judged by code and not by a model. The closest thing to a standard benchmark.
  https://arxiv.org/abs/2406.13352
- **A public red-teaming competition.** Zou and others, Gray Swan AI and the UK AI
  Security Institute (NeurIPS 2025). 22 agents, 44 scenarios, 1.8 million attacks
  sent in, more than 60,000 of them successful. Nearly all agents broke policy
  for most behaviours within 10 to 100 queries.
  https://www.aisi.gov.uk/publications/security-challenges-in-ai-agent-deployment-insights-from-a-large-scale-public-competition

## What is known about defences

- **Defences inside or around the model fall to an attacker who adapts.** Nasr,
  Carlini and others, "The Attacker Moves Second" (2025). 12 recent defences were
  bypassed, most with an attack success rate above 90%, although most had first
  reported close to zero. https://arxiv.org/abs/2510.09023
- **Defences in the system design hold better, at a cost in what the agent can
  do.** CaMeL (Debenedetti and others, 2025) solved 77% of AgentDojo tasks with
  provable security, against 84% for an undefended system.
  https://arxiv.org/abs/2503.18813
- **Design patterns.** Beurer-Kellner and others (2025). Once an agent has taken in
  untrusted input, it must be constrained so that input cannot trigger a
  consequential action. https://arxiv.org/abs/2506.08837
- **Agents Rule of Two.** Meta (31 October 2025). An agent should not have more
  than two of: untrusted input, access to private data or sensitive systems, and
  the ability to change state or communicate outside. An agent that needs all
  three should not run on its own: it needs supervision, such as a human
  approving the action. https://ai.meta.com/blog/practical-ai-agent-security/

## Where Kettle sits

- The checkpoint is a system-level control, not a model-level one. It does not try
  to make the model resist. It is fixed code outside the model that will not run a
  risky action without a yes. In the Rule of Two's terms, it is the human
  approval an agent needs when it has all three properties.
- The attack test measures the same things AgentDojo does, under plainer names:
  jobs finished with no attack, jobs finished under attack, and whether the
  attacker's action ran. It is judged by code, as AgentDojo is.
- What Kettle does not do: its attacks are fixed text written in advance, not an
  attacker who adapts. "The Attacker Moves Second" is the reason a clean result on
  a fixed set shows little, and the report says so.
- A human yes has its own weak point. A person who is asked too often, or who is
  shown a convincing request, says yes. Kettle's test uses a careful stand-in
  owner and does not measure that.

# World Seeds: A Research Program for Growing, Zoomable, Memoryful Agent Environments

## 0. Program Seed

### Core Thesis

> **A world does not need to be stored as a fixed, monolithic environment. It can be grown from a compact causal seed, expanded only where needed, and updated through experience.**

We study a new abstraction for agent world models:

\[
\text{Seed}
\xrightarrow{\text{Grow}}
\text{World}
\xrightarrow{\text{Zoom}}
\text{Experience}
\xrightarrow{\text{Consolidate}}
\text{Seed}'
\]

The long-term goal is to build agents that do not merely act inside environments, but can:

1. treat environments as externalized memory,
2. discover reusable causal structure across multiple environments,
3. represent the world at multiple resolutions,
4. selectively zoom into relevant regions or mechanisms,
5. grow detailed environments from compact latent seeds,
6. consolidate new experience back into those seeds,
7. continually improve both the agent and its model of the world.

---

# 1. Motivation

Most current agent systems separate three components:

\[
\text{Agent} + \text{Memory} + \text{Environment}
\]

The agent reasons.  
Memory stores past experience.  
The environment provides state transitions.

This separation may be unnecessarily rigid.

A more unified view is:

\[
\boxed{\text{Agent} + \text{Memoryful World}}
\]

The environment itself can encode the consequences of past interaction.  
Past actions change the state of the world, and the current world state becomes a causal compression of history.

This suggests a broader research question:

> **Can the world remember for the agent?**

---

# 2. Environment as Externalized Causal Memory

Traditional external memory stores descriptions of experience:

\[
\text{Experience}
\rightarrow
\text{Write Memory}
\rightarrow
\text{Retrieve Memory}
\]

For example:

- summaries,
- trajectories,
- vector-store entries,
- episodic memories,
- semantic notes.

Instead, a persistent environment can directly carry the effects of past actions.

Let:

\[
E_t = (x_t, m_t)
\]

where:

- \(x_t\) is the current executable or physical state,
- \(m_t\) is persistent information accumulated through interaction.

The environment evolves as:

\[
x_{t+1} = T_x(x_t, a_t)
\]

\[
m_{t+1} = T_m(m_t, x_t, a_t, x_{t+1})
\]

The key idea is:

\[
\boxed{\text{Memory update becomes part of environment transition}}
\]

Rather than retrieving a sentence saying what happened, the agent observes a world that has been changed by what happened.

### Distinction

Agent memory:

\[
M_{\text{agent}} = \text{what I learned}
\]

World memory:

\[
M_{\text{world}} = \text{what I changed}
\]

This motivates the idea of **causal memory** rather than purely semantic memory.

---

# 3. Multiple Environments as Partial Views of One World

Suppose we have many environments:

\[
E_1, E_2, \dots, E_N
\]

They should not necessarily be viewed as unrelated tasks.

They may instead be treated as different local realizations of shared underlying rules.

Two environments may look different but behave similarly under intervention.

Therefore, environment similarity should not be defined only by observation similarity:

\[
O_{E_i} \approx O_{E_j}
\]

but by similarity in causal dynamics:

\[
T_{E_i} \approx T_{E_j}
\]

or more specifically:

\[
P(s' \mid s, do(a), E_i)
\approx
P(s' \mid s, do(a), E_j)
\]

This motivates:

\[
\boxed{\text{Interventional Environment Similarity}}
\]

The purpose of multiple environments is not simply diversity.

It is to reveal invariance.

> **Variation across environments allows the model to separate laws from accidents.**

---

# 4. Reusable Causal Blocks

We hypothesize that environments can be decomposed into reusable causal blocks:

\[
E_i \approx
B_{i_1} \circ B_{i_2} \circ \dots \circ B_{i_k}
\]

Possible blocks include:

- gravity,
- collision,
- friction,
- containment,
- support,
- rigidity,
- doors,
- tools,
- communication,
- permission systems,
- file systems,
- network structure,
- social interaction rules.

A world may therefore be approximated as:

\[
\boxed{
\text{World}
=
\text{Objects}
+
\text{Relations}
+
\text{Reusable Interaction Laws}
}
\]

Each environment contains some subset of these blocks, with environment-specific parameters:

\[
E_i =
\{B_{i_1}, \dots, B_{i_k}, \theta_i\}
\]

A central goal is to discover these blocks automatically rather than manually specifying them.

### Compositional Generalization

Training may contain:

\[
A+B
\]

\[
B+C
\]

\[
A+D
\]

while testing contains:

\[
A+C+D
\]

Success on such unseen compositions would suggest that the model has learned reusable structure rather than memorized environments.

---

# 5. The God View: A Zoomable World

A fixed-resolution world model is inefficient.

The agent should not model every part of the world at maximum detail all the time.

Instead, we introduce a **God View**:

\[
E^{(0)} = \text{World}
\]

which can recursively expand:

\[
E^{(0)}
\rightarrow
\{E^{(1)}_1, E^{(1)}_2, \dots\}
\]

and continue:

\[
E^{(1)}_i
\rightarrow
\{E^{(2)}_{i1}, E^{(2)}_{i2}, \dots\}
\]

Conceptually:

```text
World
├── City
│   ├── Building
│   │   ├── Room
│   │   │   ├── Computer
│   │   │   │   ├── Process
│   │   │   │   │   └── Function
```

The important principle is:

\[
\boxed{
\text{Object at level } L
=
\text{Environment at level } L+1
}
\]

A car may be one object at a city scale and an entire environment at the mechanical scale.

---

# 6. Zoom Is More Than Resolution

Zooming in should not only provide more pixels or more tokens.

It should activate a finer causal model.

At a coarse level:

\[
W^{macro}(\text{Toronto}, \text{drive})
\rightarrow
\text{London}
\]

At a finer level:

\[
W^{car}
(\text{battery}, \text{fuel}, \text{starter}, a)
\rightarrow
\text{engine state}
\]

The appropriate level of detail depends on the task.

We therefore define a world model conditioned on scale and focus:

\[
\boxed{
W(E, a, \text{scale}, \text{focus})
}
\]

The model predicts the next world representation at the requested resolution.

---

# 7. Adaptive Zoom

The system should decide when and where to zoom.

A natural trigger is uncertainty.

If a coarse model is sufficiently confident:

\[
U(W^{coarse}(s,a)) < \tau
\]

then the agent can continue at the coarse level.

If uncertainty is high:

\[
U(W^{coarse}(s,a)) > \tau
\]

then:

\[
\boxed{\text{Zoom In}}
\]

The system recursively expands only the region or mechanism that matters.

This produces a form of adaptive computation:

\[
\text{World}
\rightarrow
\text{Region}
\rightarrow
\text{Object}
\rightarrow
\text{Component}
\]

without paying the cost of globally fine-grained simulation.

---

# 8. Zoom Out as Abstraction and Memory Consolidation

Zoom in is only half of the system.

After solving a local problem, the system should compress what it learned back into a higher-level representation.

\[
\boxed{\text{Zoom Out}}
\]

can be interpreted as:

- abstraction,
- consolidation,
- causal compression,
- long-term memory formation.

Thus:

\[
\text{Experience}
\xrightarrow{\text{Zoom Out}}
\text{Abstraction}
\]

and later:

\[
\text{Abstraction}
\xrightarrow{\text{Zoom In}}
\text{Detailed Prediction}
\]

This creates a bidirectional hierarchy between detailed experience and reusable world knowledge.

---

# 9. World Seeds

We now introduce the central abstraction of the program:

\[
\boxed{z_0 = \text{World Seed}}
\]

A seed is not merely a random number used for procedural generation.

It is a compact **developmental representation** that contains the information required to grow an environment.

A seed may include:

- causal rules,
- object prototypes,
- reusable blocks,
- relational priors,
- latent parameters,
- constraints,
- composition rules,
- growth rules.

Rather than generating an entire environment once:

\[
E = Decoder(z)
\]

we define an evolving process:

\[
E_0 = G(z_0)
\]

\[
E_{t+1} = G(E_t, a_t, \xi_t)
\]

where:

- \(a_t\) is agent interaction,
- \(\xi_t\) is internal stochasticity or exogenous events,
- \(G\) is the growth dynamics.

Thus:

\[
\boxed{
E_t =
Grow(z_0, a_{1:t}, \xi_{1:t})
}
\]

---

# 10. Causal DNA

The seed should not merely specify appearance.

It should specify how the world behaves.

A weak seed controls:

\[
seed \rightarrow appearance
\]

A stronger seed controls:

\[
\boxed{
seed \rightarrow causal\ structure
}
\]

For example:

\[
z =
\{
B_{\text{gravity}},
B_{\text{collision}},
B_{\text{friction}},
B_{\text{rigidity}},
\theta
\}
\]

Different visible environments can share the same causal seed.

This motivates the interpretation:

\[
\boxed{\text{Seed = Causal DNA}}
\]

Environment similarity may therefore arise because environments share part of their causal DNA.

---

# 11. Grow: Lazy World Construction

The fine-grained world does not need to exist in full before it is observed.

Instead, it can be generated lazily.

Start with:

\[
z_{\text{world}}
\]

If the agent focuses on a city:

\[
Grow(z_{\text{world}}, \text{city})
\rightarrow
z_{\text{city}}
\]

If the agent focuses on a room:

\[
Grow(z_{\text{city}}, \text{room})
\rightarrow
z_{\text{room}}
\]

This gives:

\[
\boxed{\text{Lazy World Generation}}
\]

Only the task-relevant parts of the world need to be instantiated at high resolution.

This can dramatically reduce computation while preserving the ability to reason locally in detail.

---

# 12. Seeds Can Mature

A seed should not remain fixed.

Experience can modify it:

\[
z_t
\rightarrow
z_{t+1}
\]

via:

\[
z_{t+1}
=
Consolidate(z_t, experience_t)
\]

The loop becomes:

\[
z_t
\xrightarrow{\text{Grow}}
E_t
\xrightarrow{\text{Interact}}
experience_t
\xrightarrow{\text{Consolidate}}
z_{t+1}
\]

Thus the seed becomes:

\[
\boxed{
\text{compressed lifetime experience}
}
\]

This changes the role of memory.

Traditional memory:

\[
Memory
\rightarrow
\text{changes agent behavior}
\]

Seed memory:

\[
\boxed{
Memory
\rightarrow
\text{changes how future worlds unfold}
}
\]

Past experience does not merely alter the policy.  
It alters the world representation the agent uses to interpret future situations.

---

# 13. From Episodic Memory to World Knowledge

Suppose the agent observes:

\[
E_7:
\text{pushing a wooden block moves it 5 cm}
\]

\[
E_{23}:
\text{pushing a metal block moves it 2 cm}
\]

\[
E_{91}:
\text{pushing a plastic block moves it 7 cm}
\]

The individual experiences are situated memories.

Across environments, the agent can abstract:

\[
\text{force} \rightarrow \text{acceleration}
\]

This suggests a pipeline:

\[
\text{Episodic World Memory}
\rightarrow
\text{Cross-Environment Invariance}
\rightarrow
\text{Reusable Causal Block}
\]

The seed becomes a compact store of structured, reusable world knowledge.

---

# 14. A Hierarchical Causal Graph

The real world is not a pure tree.

An entity may participate in multiple systems.

A person can belong simultaneously to:

- a family,
- a company,
- a city,
- a traffic system,
- an economic system.

Therefore, the long-term representation should be a:

\[
\boxed{\text{Hierarchical Causal Graph}}
\]

with two broad classes of edges.

### Horizontal edges

\[
E_i^{(l)}
\leftrightarrow
E_j^{(l)}
\]

represent:

- interaction,
- similarity,
- communication,
- causality,
- shared constraints.

### Vertical edges

\[
E_i^{(l)}
\leftrightarrow
E_j^{(l+1)}
\]

represent:

- contains,
- abstracts,
- explains,
- expands,
- zooms into.

The world is therefore a graph of environments at multiple resolutions.

---

# 15. Multi-Agent Extension

Multiple agents can interact with different parts of the world while sharing the same evolving seed.

For agents:

\[
A_1, A_2, \dots, A_n
\]

each may explore different regions:

\[
A_1 \rightarrow E_1
\]

\[
A_2 \rightarrow E_2
\]

\[
A_3 \rightarrow E_3
\]

and consolidate discoveries into:

\[
z_{\text{shared}}
\]

The shared seed becomes:

\[
\boxed{\text{Collective World Memory}}
\]

This may reduce the need for pairwise communication.

Rather than:

\[
A_i \leftrightarrow A_j
\]

every agent can interact through:

\[
A_i \leftrightarrow z_{\text{shared}}
\]

This resembles stigmergic coordination: agents communicate indirectly by changing the shared world representation.

---

# 16. Seed Mutation and Curriculum Generation

If a seed represents causal structure, it can be modified.

\[
z' = Mutate(z)
\]

Possible mutations include:

- lower gravity,
- different friction,
- missing tools,
- new failure modes,
- changed permissions,
- altered object relations,
- new communication constraints.

Then:

\[
Grow(z')
\rightarrow
E'
\]

This naturally produces structured curriculum generation.

Once an agent masters \(z\), the system can produce:

\[
z + \Delta z
\]

to create a slightly harder or compositionally different environment.

---

# 17. Seed Crossover and World Breeding

Seeds can also be composed.

Let:

\[
z_A =
\{
B_{\text{navigation}},
B_{\text{traffic}}
\}
\]

and:

\[
z_B =
\{
B_{\text{tool}},
B_{\text{repair}}
\}
\]

Then:

\[
z_C = z_A \oplus z_B
\]

could generate an environment requiring an agent to:

1. navigate to a destination,
2. diagnose a machine,
3. repair it using tools.

This leads to:

\[
\boxed{\text{Compositional World Breeding}}
\]

Synthetic environments become structured recombinations of causal knowledge rather than arbitrary LLM-generated tasks.

---

# 18. Core Architecture

A minimal conceptual system contains four modules.

## 18.1 Seed Memory

\[
S_t
\]

Stores compact structured world knowledge.

## 18.2 World Grower

\[
G(S_t, focus, scale)
\rightarrow
E_t^{(l)}
\]

Expands relevant parts of the seed into an environment at a chosen resolution.

## 18.3 Agent / Planner

\[
\pi(a_t \mid E_t^{(l)}, goal)
\]

Acts within the generated environment.

## 18.4 Consolidator

\[
C(S_t, trajectory)
\rightarrow
S_{t+1}
\]

Compresses interaction experience into the seed.

Overall:

\[
\boxed{
S_t
\xrightarrow{Grow}
E_t
\xrightarrow{Interact}
Trajectory
\xrightarrow{Consolidate}
S_{t+1}
}
\]

---

# 19. A Learned World Model Formulation

A conventional world model predicts:

\[
W_\phi(s_t, a_t)
\rightarrow
\hat{s}_{t+1}
\]

A zoomable seed-based model instead predicts:

\[
\boxed{
W_\phi(
S_t,
focus_t,
scale_t,
a_t
)
\rightarrow
(
\hat{E}_{t+1}^{(l)},
\hat{S}_{t+1}
)
}
\]

Potentially, the model does not need to predict full raw observations.

It may predict:

- causal state,
- task-relevant latent state,
- progress,
- uncertainty,
- block activation,
- local transition structure.

This suggests a major research question:

> **What should a world model predict at each scale?**

---

# 20. Key Research Questions

## RQ1. Environment as Memory

Can persistent environment state replace or reduce explicit episodic memory?

## RQ2. Cross-Environment Structure

Can reusable causal blocks be discovered automatically from multiple environments?

## RQ3. Environment Similarity

Can similarity be defined through intervention and transition behavior rather than observation-level appearance?

## RQ4. Adaptive Zoom

Can an agent learn where and when to increase world-model resolution?

## RQ5. Causal Coarse-Graining

What information must survive when compressing a detailed environment into a coarse representation?

## RQ6. Seed Learning

Can a compact seed encode enough causal structure to regenerate task-relevant environments?

## RQ7. Seed Consolidation

Can interaction experience update the seed without catastrophic interference?

## RQ8. Compositional Generalization

Can known blocks be recombined to predict unseen environment compositions?

## RQ9. Multi-Agent World Memory

Can multiple agents jointly improve a shared seed through distributed exploration?

## RQ10. Self-Improvement

Can the agent and its world seed co-evolve through interaction, failure discovery, and environment mutation?

---

# 21. Core Hypotheses

### H1. Causal State Beats Raw History

A persistent causal world state can summarize long interaction histories more efficiently than storing full trajectories.

### H2. Cross-Environment Invariance Enables Abstraction

Shared transition structure across diverse environments enables discovery of reusable causal blocks.

### H3. Adaptive Resolution Improves Efficiency

A zoomable world model can achieve comparable or better planning quality with less computation than uniformly fine-grained simulation.

### H4. Seed-Based Worlds Improve Generalization

A compositional seed representation enables faster adaptation to unseen environments than monolithic environment embeddings.

### H5. Consolidation Enables Continual World Learning

Updating seeds with experience allows the world model to improve over time without storing all past trajectories.

---

# 22. Minimal Prototype

A first prototype should avoid full physical simulation.

A small symbolic or tool-based environment is enough.

## Possible Domain

A grid / room / object world with:

- doors,
- keys,
- containers,
- movable blocks,
- tools,
- switches,
- hidden dependencies.

Each environment can be defined by causal blocks.

Example blocks:

```text
gravity
collision
openable
lockable
container
requires-key
pushable
fragile
tool-required
```

Each task samples a composition of blocks.

The system learns:

1. a seed representation,
2. a grow function,
3. a zoom policy,
4. a transition model,
5. a consolidation function.

---

# 23. Baselines

Useful baselines include:

### Stateless Agent

\[
\pi(o_t)
\]

### Full-Trajectory Agent

\[
\pi(o_t, \tau_{1:t})
\]

### Retrieval Memory Agent

\[
\pi(o_t, Retrieve(M, q_t))
\]

### Flat World Model

\[
W(s_t, a_t) \rightarrow s_{t+1}
\]

### Monolithic Environment Embedding

\[
z_E = Encoder(E)
\]

### Fixed-Hierarchy World Model

Uses predefined levels but no learned adaptive zoom.

### World Seed Model

\[
\boxed{
Seed
+
Grow
+
Zoom
+
Consolidate
}
\]

---

# 24. Evaluation Dimensions

## Task Performance

- success rate,
- reward,
- long-horizon completion.

## Generalization

- unseen environments,
- unseen block combinations,
- unseen scales,
- unseen task compositions.

## Efficiency

- context tokens,
- simulated states,
- model calls,
- environment interactions,
- rollout cost.

## Memory Quality

- retained causal knowledge,
- forgetting,
- interference,
- transfer across tasks.

## World Model Quality

- transition prediction,
- calibration,
- uncertainty,
- causal consistency.

## Zoom Quality

- whether the model zooms into the correct region,
- whether unnecessary detail is avoided,
- whether local information is successfully compressed back.

## Exploitability

- whether the agent discovers and exploits inaccuracies in the learned world model.

---

# 25. Long-Term Research Program

The program can naturally branch into several papers.

## Paper A — Environment as Causal Memory

Study whether persistent world state can replace explicit episodic memory.

## Paper B — Cross-Environment Causal Block Discovery

Learn reusable dynamics modules from multiple interactive environments.

## Paper C — Zoomable World Models

Learn adaptive coarse-to-fine world modeling for agent planning.

## Paper D — World Seeds

Learn compact developmental seeds capable of growing interactive environments.

## Paper E — Consolidation

Study how experience updates the seed and becomes reusable world knowledge.

## Paper F — Multi-Agent Shared Seeds

Use a shared world seed as collective memory for distributed agents.

## Paper G — Self-Evolving Worlds

Co-evolve agents and environment seeds through mutation, adversarial discovery, and curriculum generation.

---

# 26. Program-Level Vision

The conventional view is:

\[
\text{Agent acts in a fixed world}
\]

Our proposed view is:

\[
\boxed{
\text{Agent and world representation develop together}
}
\]

The agent does not maintain a complete simulation of reality.

Instead, it maintains a compact seed.

The seed grows task-relevant worlds.

The agent zooms into uncertain or important regions.

Experience changes the generated environment.

The environment records causal consequences.

Those consequences are compressed back into the seed.

Across many environments, shared causal structure becomes reusable world knowledge.

The cycle is:

\[
\boxed{
Seed
\rightarrow
Grow
\rightarrow
Zoom
\rightarrow
Interact
\rightarrow
Remember
\rightarrow
Abstract
\rightarrow
Consolidate
\rightarrow
Seed'
}
\]

---

# 27. One-Sentence Program Statement

> **We aim to build agents whose world models behave like growing causal memories: compact seeds that recursively generate task-relevant environments, zoom into uncertainty, discover reusable structure across worlds, and consolidate experience back into increasingly capable representations of reality.**

---

# 28. Working Names

### Research Program

**World Seeds**

### Possible System Names

- WorldSeed
- SeedWorld
- GrowWorld
- WorldTree
- CausalSeed
- WorldAtlas
- ZoomWorld
- SeedAtlas
- Growing Worlds

### Possible Paper Titles

**World Seeds: Growing Interactive Environments from Compositional Causal Memory**

**Growing Worlds: Developmental World Models for Continually Learning Agents**

**Zoomable World Models: Adaptive Multi-Resolution Environments for Agent Planning**

**From Environments to a World: Learning Composable Causal Memory Across Interactive Environments**

---

# 29. Guiding Principles

1. **Do not model everything at maximum resolution.**
2. **Let interaction determine what deserves detail.**
3. **Treat persistent world state as memory.**
4. **Use environment diversity to discover invariance.**
5. **Represent invariance as reusable causal blocks.**
6. **Allow every object to become an environment when zoomed into.**
7. **Grow detailed worlds lazily from compact seeds.**
8. **Compress detailed experience back into higher-level abstractions.**
9. **Let seeds mature through experience.**
10. **Measure whether the resulting model improves planning, transfer, and self-improvement—not merely prediction accuracy.**

---

# 30. The Seed

The entire program can be reduced to one loop:

\[
\boxed{
S_t
\xrightarrow{\text{Grow}}
E_t
\xrightarrow{\text{Zoom}}
E_t^{local}
\xrightarrow{\text{Act}}
Experience_t
\xrightarrow{\text{Consolidate}}
S_{t+1}
}
\]

with many environments providing the evidence needed to discover shared causal structure:

\[
\boxed{
\{E_1,E_2,\dots,E_N\}
\rightarrow
\{B_1,B_2,\dots,B_K\}
\rightarrow
S
}
\]

The central bet is simple:

> **A sufficiently good seed should not memorize every world. It should learn how worlds grow.**

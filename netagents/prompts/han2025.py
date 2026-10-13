"""Prompts of LbMAS: Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture
(arXiv 2507.01701v1, 2025), transcribed from the paper's Figures 4-6 (Appendix A.3), with the paper's own
wording, spelling and punctuation; the authors' code had not been released. Variables are in {braces}; the
paper's doubled braces {{...}} (literal braces in its templates) are kept as single braces here.
"""

SYSTEM = ("You are {role_name} cooperating with other agents to solve the problem. The problem is:{question}.\n"
          "There is a blackboard that everyone of you can read or write messages.")

DECIDER = ("If you think the messages on the blackboard enough to get the final answer then You should output the "
           "final answer with your answer in the form {the final answer is boxed[answer]}, at the end of your "
           "response. otherwise you need other agents provide more information then say "
           "{\"continue, waiting for more information\"} and wait other agent giving new factors. do not output "
           "other information.")

PLANNER = ("Generate plans to solve the original problem based on blackboard contents. Strictly follow the json "
           "format as follows: {\"[problem]\":string //describe the problem,\"[planning]\":string //was the solving "
           "plan of the problem}, If there already have plan or problem is simple enough to solve then say "
           "{\"there is no need to decompose tasks, waiting for more information\"}. Do not solve the task.")

CLEANER = ("If you think there are messages on the blackboard useless or redundant, you should output useless "
           "messages and your explanation. your output should follow the json format follow the form: "
           "{\"clean list\":[{\"useless message\":string //write useless message exactly, \"explanation\":string "
           "//was your explanation why the message is useless or redundant}]}. If you think there are no useless "
           "messages then you should write {\"no useless messages, waiting for more information\"} and wait for "
           "other agents to provide more information.")

CRITIC = ("If you think the messages on the blackboard are wrong or misleading, your output should Strictly follow "
          "the json format as follows: {\"critic list\":[{\"wrong message\":string //write whose message and which "
          "message is wrong, \"explanation\":string //was your explanation why the message is wrong}]}. Otherwise "
          "you think there are no wrong messages then you should write {\"no problem, waiting for more "
          "information\"} and wait for other agents to provide more information.")

CONFLICT_RESOLVER = ("If you think other agents' messages on the blackboard have conflicts, you should output all "
                     "conflict agents and their messages. Output strictly follow the json format as follows: "
                     "\n{\"conflict list\":[{\"agent\":string //was the name of conflict agent,\"message\"string "
                     "//was the conflict message of agent on the blackboard}]}\n. Otherwise you think there are no "
                     "conflicts then you should write {\"no conflicts, waiting for more information\"} .Do not "
                     "output other information.")

GENERATED_EXPERT = ("You are an excellent {role} described as {roles_description}. Based on your expert knowledge and "
                    "contents currently on the blackboard, solve the problem, output your ideas and information you "
                    "want to write on the blackboard. It's not necessary to fully agree with viewpoint on the "
                    "blackboard. Your output should strictly follow the json form:\n {\"output\":\"\"}.")

AGENT_GENERATION = ("You are provided a question. Give me a list of 1 to 3 expert roles that most helpful in solving "
                    "question. Question: {question}. Only give me the answer as a dictionary of roles in the Python "
                    "programming format with a short description for each role. Strictly follow the answer format "
                    "below: \nAnswer: {\"[role name 1]\": \"[description 1]\", \"[role name 2]\": \"[description "
                    "2]\", \"[role name 3]\": \"[description 3]\"}")

CONTROL_UNIT = ("Your task is to schedule other agents to cooperate and solve the given problem. The agent names and "
                "descriptions are listed below:\n{role_list}. The given problem is:{question}. Agents are sharing "
                "information on the blackboard. Based on the contents existed on the blackboard, you need to choose "
                "suitable agents from agent list to write on the blackboard. Remember Output the agent names in the "
                "json form: \"{\"chosen agents\":[list of agent name]}")

PREDEFINED = {"decider": DECIDER, "planner": PLANNER, "critic": CRITIC, "cleaner": CLEANER,
              "conflict_resolver": CONFLICT_RESOLVER}
DESCRIPTIONS = {  # the paper's descriptions of the predefined agents (Section 3.2)
    "decider": "assesses whether messages on the blackboard are enough to yield the final solution; if so, gives the "
               "solution and the blackboard cycle stops",
    "planner": "makes plans to solve the query, and decomposes the query into smaller tasks when it is complex",
    "critic": "points out errors in messages on the blackboard and forces relevant agents to rethink their output",
    "cleaner": "detects useless or redundant messages and removes them",
    "conflict_resolver": "detects contradictions among messages on the blackboard and names the agents that have "
                         "conflicting messages",
}

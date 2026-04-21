from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from services.chat.app.workflow.llm_chain import build_chain
from langgraph.config import get_stream_writer
from langchain_core.runnables.config import RunnableConfig
from services.chat.app.prompts import BASE_PROMPT
import json

# async def generate_response(state):

#     chain = build_chain(system_prompt=BASE_PROMPT)

#     collected = []

#     # async for chunk in chain.astream({
#     #     "chat_input": state["chat_input"]
#     # }):
#     #     token = chunk.content if hasattr(chunk, "content") else str(chunk)

#     #     collected.append(token)

#     #     # ✅ stream token
#     #     yield {
#     #         "chat_response_stream": token
#     #     }

#     # full_text = "".join(collected)

#     # # ✅ final output
#     # yield {
#     #     "chat_response": full_text
#     # }
#     # Prepend system prompt if not already present
#     messages = state["messages"]
#     if not any(isinstance(m, SystemMessage) for m in messages):
#         messages = [SystemMessage(content=BASE_PROMPT.prompt)] + list(messages)


#     response = await chain.ainvoke(messages)
    

#     return {"messages": [AIMessage(content=response.content)]}


# async def generate_response(state, config: RunnableConfig):
#     messages = state["messages"]

#     # System message is handled by the prompt template now, don't prepend manually
#     chain = build_chain(system_prompt=BASE_PROMPT)

#     # ✅ Fix: pass messages under the correct key matching MessagesPlaceholder
#     response = await chain.ainvoke({"messages": messages}, config=config)

#     return {"messages": [AIMessage(content=response.content)]}

async def generate_response(state, config: RunnableConfig):
    messages = state["messages"]
    write = get_stream_writer()  # ✅ get the custom stream writer

    chain = build_chain(system_prompt=BASE_PROMPT)

    collected = []

    # ✅ astream instead of ainvoke — emits tokens as they arrive
    async for chunk in chain.astream({"messages": messages, "claim_context": state["claim_context"]}, config=config):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            collected.append(token)
            write({"token": token})  # ✅ push token to custom stream

    full_response = "".join(collected)
    return {"messages": [AIMessage(content=full_response)]}
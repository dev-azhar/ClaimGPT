from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama

from services.chat.app.prompts import BASE_PROMPT
from services.chat.app.config import settings



def get_chat_model(temperature: float = 0.7, model_name: str = settings.ollama_model) -> ChatOllama:
    return ChatOllama(
        model=model_name,
        temperature=temperature,
    )

def build_chain(system_prompt: str = BASE_PROMPT.prompt, model_name: str = settings.ollama_model):
    model = get_chat_model(model_name=model_name)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),  
        ],
        template_format="jinja2",
    )

    return prompt | model
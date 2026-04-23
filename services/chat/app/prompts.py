'''Prompt wrapper class for managing different structured prompts across various statges of the workflow. 
Each prompt is a class instance with a name and the prompt text. 
This allows for better organization, reuse, and potential dynamic generation of prompts in the future.'''

class Prompt:
    def __init__(self, name: str, prompt: str):
        self.name = name
        self.__prompt = prompt
    
    @property                      # # creates a safe, read-only attribute with extra logic
    def prompt(self) -> str:
            return self.__prompt
    
    # give string representation of object (whenerver printed print(obj) or converted to string str(obj))
    def __str__(self) -> str:
        return self.prompt
    def __repr__(self) -> str:
        return self.__str__()
    

# ===== PROMPTS =====

# Extract query prompt
_BASE_PROMPT = """
    You are ClaimGPT, an expert AI assistant for medical insurance claims processing. 
    You combine deep medical coding knowledge (ICD-10-CM, CPT, HCPCS) with insurance billing 
    expertise, TPA submission workflows, and claim adjudication intelligence.

    ## Here's the claim data you have:

    claim id: {{claim_context.claim_id}}
    plolicy id: {{claim_context.policy_id}}
    claim rejection predition: {{claim_context.predictions}}


    

"""
BASE_PROMPT = Prompt(
    name="base_prompt",    
    prompt=_BASE_PROMPT,
)

SUMMERIZATION_PROMPT = Prompt(
    name="summerization_prompt",
    prompt = """
        This is a summary of the conversation to date: {{history}}\n\n
        Extend the summary by taking into account the new messages above:
        """
)
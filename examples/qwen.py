from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.generation import GenerationConfig
from together_worker.fast_inference import FastInferenceInterface

class QwenModel(FastInferenceInterface):
    def setup(self, args):
        self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen-7B-Chat", trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen-7B-Chat", device_map="auto", trust_remote_code=True).eval()
        self.model.generation_config = GenerationConfig.from_pretrained("Qwen/Qwen-7B-Chat", trust_remote_code=True) 
        
    def dispatch_request(self, args, env):
        prompt = args[0]["prompt"]
        response, history = self.model.chat(self.tokenizer, prompt, history=None)
        return {
            "choices": [ { "text": response } ],
        }

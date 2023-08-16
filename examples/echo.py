from together_worker.fast_inference import FastInferenceInterface

class Echo(FastInferenceInterface):
    def setup(self, args):
        self.message = args.get("message", " to you to.")

    def dispatch_request(self, args, env):
        prompt = args[0]["prompt"]
        return {
            "choices": [ { "text": prompt + self.message } ],
        }

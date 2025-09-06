from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

model_name = "bolbolzaban/gpt2-persian"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)
generator = pipeline('text-generation', model=model, tokenizer=tokenizer, config={'max_length': 256})

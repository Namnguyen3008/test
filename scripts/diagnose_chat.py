import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")

from src.agents.graph import agent
from src.agents.nodes.example_node import (
    emergency_node,
    generate_node,
    normalize_node,
    retrieve_node,
    validate_node,
    _routing_prompt,
)
from src.services.routing import get_routing_retriever
from src.services.llm import get_llm

async def run_diagnostics():
    queries = [
        "Trẻ 3 tuổi sốt cao li bì",
        "Tôi bị đau đầu từ sáng nay",
        "Tôi muốn khám răng",
        "Tôi bị đau dạ dày sau khi ăn",
        "Tôi bị ngứa da nổi mề đay",
        "Tôi muốn đặt lịch khám nội tổng quát",
        "Tôi đau mắt đỏ 3 ngày nay"
    ]
    
    for q in queries:
        print(f"\n=======================================================")
        print(f"QUERY: {q}")
        print(f"=======================================================")
        state = {"query": q}
        
        # Step 1: Normalize
        state.update(await normalize_node(state))
        print(f"[1] Normalize: {state.get('query')}")
        
        # Step 2: Emergency
        emerg_res = await emergency_node(state)
        state.update(emerg_res)
        print(f"[2] Emergency: emergency={state.get('emergency')}")
        if state.get("emergency"):
            print(f"    Emergency Response: {state.get('response')}")
            print(f"    Metadata: {state.get('metadata')}")
            continue
            
        # Step 3: Retrieve
        ret_res = await retrieve_node(state)
        state.update(ret_res)
        records = state.get("retrieval_records", [])
        print(f"[3] Retrieve: records_count={len(records)}, mode={state.get('retrieval_mode')}")
        print(f"    Allowed specialties: {state.get('allowed_specialty_ids')}")
        print(f"    Valid sources: {state.get('valid_source_ids')}")
        if records:
            for i, r in enumerate(records[:3]):
                print(f"    Record {i+1}: ID={r.get('record_id')}, Spec={r.get('specialty_id')}, Sources={r.get('source_ids')}")
                print(f"      Text: {r.get('text')[:100]}...")
        else:
            print(f"    NO RECORDS FOUND! Response: {state.get('response')}, Error: {state.get('error')}")
            print(f"    Metadata: {state.get('metadata')}")
            continue
            
        # Step 4: Generate
        prompt = _routing_prompt(state)
        print(f"[4] Routing Prompt sent to LLM:\n{prompt[:300]}...\n")
        try:
            gen_res = await generate_node(state)
            state.update(gen_res)
            print(f"[4] LLM Output:\n{state.get('model_output')}")
            print(f"    LLM Meta: {state.get('metadata')}")
        except Exception as e:
            print(f"[4] LLM Exception: {e}")
            import traceback
            traceback.print_exc()
            continue
            
        # Step 5: Validate
        val_res = await validate_node(state)
        state.update(val_res)
        print(f"[5] Validate: Response=\n{state.get('response')}")
        print(f"    Error: {state.get('error')}")
        print(f"    Final Metadata:\n{json.dumps(state.get('metadata', {}), ensure_ascii=False, indent=2)}")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())

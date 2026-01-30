"""LangGraph workflow definition for style learning."""

from langgraph.graph import END, StateGraph

from app.langgraph.nodes import (
    analyze_patterns,
    analyze_tone,
    analyze_vocabulary,
    generate_summary,
    load_memory,
    merge_analysis,
    store_memory,
)
from app.langgraph.state import StyleLearningState


def create_style_learning_graph() -> StateGraph:
    """Create and compile the style learning workflow graph.

    Workflow:
        load_memory → [analyze_tone, analyze_vocabulary, analyze_patterns] (parallel)
            → merge_analysis → generate_summary → store_memory → END
    """
    # Create the graph
    workflow = StateGraph(StyleLearningState)

    # Add nodes
    workflow.add_node("load_memory", load_memory)
    workflow.add_node("analyze_tone", analyze_tone)
    workflow.add_node("analyze_vocabulary", analyze_vocabulary)
    workflow.add_node("analyze_patterns", analyze_patterns)
    workflow.add_node("merge_analysis", merge_analysis)
    workflow.add_node("generate_summary", generate_summary)
    workflow.add_node("store_memory", store_memory)

    # Set entry point
    workflow.set_entry_point("load_memory")

    # Add edges - parallel analysis after loading memory
    workflow.add_edge("load_memory", "analyze_tone")
    workflow.add_edge("load_memory", "analyze_vocabulary")
    workflow.add_edge("load_memory", "analyze_patterns")

    # All analysis nodes lead to merge
    workflow.add_edge("analyze_tone", "merge_analysis")
    workflow.add_edge("analyze_vocabulary", "merge_analysis")
    workflow.add_edge("analyze_patterns", "merge_analysis")

    # After merge, generate summary and store
    workflow.add_edge("merge_analysis", "generate_summary")
    workflow.add_edge("generate_summary", "store_memory")
    workflow.add_edge("store_memory", END)

    return workflow


# Compile the graph for reuse
_compiled_graph = None


def get_compiled_graph():
    """Get the compiled graph instance."""
    global _compiled_graph
    if _compiled_graph is None:
        workflow = create_style_learning_graph()
        _compiled_graph = workflow.compile()
    return _compiled_graph


async def run_style_learning(
    user_id: str,
    message_body: str,
    message_subject: str = "",
    is_reply: bool = False,
) -> StyleLearningState:
    """Run the style learning workflow for a message.

    Args:
        user_id: Unique identifier for the user
        message_body: The email message body to learn from
        message_subject: Optional email subject
        is_reply: Whether this message is a reply

    Returns:
        The final state after processing
    """
    graph = get_compiled_graph()

    initial_state: StyleLearningState = {
        "user_id": user_id,
        "message_body": message_body,
        "message_subject": message_subject,
        "is_reply": is_reply,
        "existing_profile": None,
        "samples_count": 0,
        "is_duplicate": False,
        "error": None,
    }

    # Run the graph
    final_state = await graph.ainvoke(initial_state)

    return final_state

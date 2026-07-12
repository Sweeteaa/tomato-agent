from app.services.conversation_service import append_conversation, get_conversation
from app.services.graph_service import run_graph_stream
from app.services.file_service import extract_file_content


def chat_with_agent_stream(query: str, conv_id: str = None, files: list = None):
    file_info = []
    uploaded_filenames = []
    
    if files and len(files) > 0:
        for file in files:
            content = extract_file_content(file["content"], file["filename"])
            file_info.append(f"【文件: {file['filename']}】\n{content}\n")
            uploaded_filenames.append(file["filename"])
    
    context_messages = []
    if conv_id:
        conv_data = get_conversation(conv_id)
        if conv_data and conv_data.get("messages"):
            for msg in conv_data["messages"]:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    context_messages.append(f"用户: {content}")
                elif role == "assistant":
                    context_messages.append(f"助手: {content}")
    
    if file_info:
        query_with_files = f"{query}\n\n以下是上传的文件内容，请根据文件内容回答问题：\n{'---\n'.join(file_info)}"
    else:
        query_with_files = query
    
    if context_messages:
        context_str = "\n".join(context_messages[-20:])
        query_with_context = f"""以下是历史对话上下文：

{context_str}

请基于上述上下文，回答用户最新的问题：

{query_with_files}"""
    else:
        query_with_context = query_with_files

    final_result = None
    
    for event in run_graph_stream(query_with_context, conv_id):
        if event["type"] == "done":
            final_result = event
            event["files_uploaded"] = uploaded_filenames
        else:
            yield event

    if final_result:
        conv_data = append_conversation(
            query_with_files,
            final_result["response"],
            final_result["tool_executions"],
            conv_id
        )
        final_result["conversation_id"] = conv_data["id"]
        yield final_result
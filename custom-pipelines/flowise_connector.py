"""
title: Flowise Connector
author: DaveJ
date: 2025-02-13
version: 1.0
license: MIT
description: A pipeline that connects to flowise.
requirements: flowise
"""

from typing import List, Union, Generator, Iterator, Optional
from flowise import Flowise, PredictionData
from pydantic import BaseModel
import os
import json


class CitationCache:
    def __init__(self):
        self._cache = {}

    def set_citations(self, citation_id: str, citations: list) -> None:
        self._cache[citation_id] = citations

    def add_citation(self, citation_id: str, citation: dict) -> None:
        if citation_id in self._cache:
            self._cache[citation_id].append(citation)
        else:
            self._cache[citation_id] = [citation]

    def get_citations(self, citation_id: str) -> list:
        return self._cache.get(citation_id, None)


class Pipeline:
    class Valves(BaseModel):
        FLOWISE_URL: str
        FLOWISE_CHAT_FLOW_ID: str

        FLOWISE_CITATION_PAGE_TEXT: str
        FLOWISE_CITATION_FILE_NAME_PATH: str
        FLOWISE_CITATION_PAGE_NUMBER_PATH: str
        FLOWISE_CITATION_PAGE_CONTENT_PATH: str

    def __init__(self):
        # import debugpy
        # debugpy.listen(("0.0.0.0", 5678))

        self.valves = self.Valves(
            **{
                "FLOWISE_URL": os.getenv("FLOWISE_URL", "http://localhost:3000"),
                "FLOWISE_CHAT_FLOW_ID": os.getenv("FLOWISE_CHAT_FLOW_ID", ""),
                "FLOWISE_CITATION_PAGE_TEXT": os.getenv("FLOWISE_CITATION_PAGE_TEXT", "Page"),

                "FLOWISE_CITATION_FILE_NAME_PATH": os.getenv("FLOWISE_CITATION_FILE_NAME_PATH", "metadata.source"),
                "FLOWISE_CITATION_PAGE_NUMBER_PATH": os.getenv("FLOWISE_CITATION_PAGE_NUMBER_PATH", "metadata.loc.pageNumber"),
                "FLOWISE_CITATION_PAGE_CONTENT_PATH": os.getenv("FLOWISE_CITATION_PAGE_CONTENT_PATH", "pageContent"),
            }
        )

        self.name = os.getenv(
            "FLOWISE_CONNECTOR_PIPELINE_NAME", "Flowise Connector")

        self.flowise_client = Flowise(self.valves.FLOWISE_URL)

        self.citation_cache = CitationCache()

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def inlet(self, body: dict, user: dict) -> dict:
        body["flowise_session_id"] = body["metadata"]["chat_id"]
        body["message_id"] = body["metadata"]["message_id"]

        return body

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:

        autocompleteText = """### Task:\nYou are an autocompletion system. Continue the text in `<text>` based on the **completion type** in `<type>` and the given language.  \n\n###"""
        if self.userMessageStartsWith(user_message, autocompleteText):
            return ""

        titleGenerationText = """### Task:\nGenerate a concise, 3-5 word title with an emoji summarizing the chat history.\n###"""
        if self.userMessageStartsWith(user_message, titleGenerationText):
            return "Flowise Chat"

        tagsGenerationText = """### Task:\nGenerate 1-3 broad tags categorizing the main themes of the chat history, along with 1-3 more specific subtopic tags.\n\n###"""
        if self.userMessageStartsWith(user_message, tagsGenerationText):
            return ""

        chat_id = body.get("flowise_session_id")
        message_id = body.get("message_id")

        if body.get("stream"):
            completion = self.flowise_client.create_prediction(
                PredictionData(
                    chatflowId=self.valves.FLOWISE_CHAT_FLOW_ID,
                    question=user_message,
                    streaming=True,
                    chatId=chat_id
                )
            )

            for chunk in completion:
                response_json_chunk = json.loads(chunk)
                event_type = response_json_chunk.get("event")

                if event_type == "token":
                    text = response_json_chunk.get("data")
                    yield text
                elif event_type == "sourceDocuments":
                    self.saveCitation(
                        message_id, response_json_chunk.get("data"))
        else:
            completion = self.flowise_client.create_prediction(
                PredictionData(
                    chatflowId=self.valves.FLOWISE_CHAT_FLOW_ID,
                    question=user_message,
                    streaming=False,
                    chatId=chat_id
                )
            )

            for completion_response in completion:
                self.saveCitation(
                    message_id, completion_response["sourceDocuments"])
                yield completion_response["text"]

    async def outlet(self, body: dict, user: dict) -> dict:
        body["messages"][-1]["sources"] = self.citation_cache.get_citations(
            body.get("id"))

        return body

    def saveCitation(self, message_id: str, source_documents: dict):
        for source_document in source_documents:
            document = {}

            file_name = os.path.basename(self.getNestedValue(
                source_document, self.valves.FLOWISE_CITATION_FILE_NAME_PATH))
            page_number = self.getNestedValue(
                source_document, self.valves.FLOWISE_CITATION_PAGE_NUMBER_PATH)
            page_content = self.getNestedValue(
                source_document, self.valves.FLOWISE_CITATION_PAGE_CONTENT_PATH)

            document["document"] = [page_content]
            document["metadata"] = [{
                "source": f"{file_name} - {page_number}"
            }]
            document["source"] = {
                "name": f"{file_name} - {self.valves.FLOWISE_CITATION_PAGE_TEXT} {page_number}"
            }

            self.citation_cache.add_citation(message_id, document)

    def getNestedValue(self, data: dict, path: str, separator: str = "."):
        keys = path.split(separator)
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key)
            else:
                return None
        return data

    def userMessageStartsWith(self, user_message: str, text_to_compare: str):
        if user_message.startswith(text_to_compare):
            return True
        else:
            return False

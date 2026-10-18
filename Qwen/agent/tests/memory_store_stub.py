"""只用于测试的存储替身，避免回归测试访问真实全局记忆。"""
import copy
from agent.entities.memory import MemorySnapshot, MemoryConflictError


class MemoryStoreStub:
    def __init__(self):
        self.messages = []
        self.revision = 0

    def load(self):
        return MemorySnapshot(copy.deepcopy(self.messages), self.revision)

    def save(self, expected_revision, messages):
        if expected_revision != self.revision:
            raise MemoryConflictError("test conflict")
        self.messages = copy.deepcopy(messages)
        self.revision += 1
        return self.revision

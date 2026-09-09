from __future__ import annotations

from dataclasses import dataclass

from backend.app.application.services import CredentialVault, PlatformService, seed
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.infrastructure.repository import Repository
from backend.app.infrastructure.runtime import KubernetesRuntime, LocalSandboxRuntime
from backend.app.worker import CommandWorker


@dataclass
class Container:
    settings: Settings
    database: Database
    repository: Repository
    service: PlatformService
    runtime: object
    worker: CommandWorker

    @classmethod
    def build(cls, settings: Settings) -> "Container":
        database = Database(settings.database_path)
        repository = Repository(database)
        seed(repository)
        runtime = KubernetesRuntime(settings.kubernetes_namespace) if settings.runtime_backend == "kubernetes" else LocalSandboxRuntime()
        service = PlatformService(repository, settings.package_dir, CredentialVault(settings.master_key), runtime)
        worker = CommandWorker(repository, service, runtime, settings.worker_poll_seconds)
        return cls(settings, database, repository, service, runtime, worker)

import logging
import multiprocessing
from multiprocessing.connection import wait

from logging_config import configure_logging

logger = logging.getLogger(__name__)


def run_processes(processes) -> int:
    exit_code = 1
    try:
        for process in processes:
            process.start()
            logger.info("child_started child=%r pid=%r", process.name, process.pid)

        ready = wait([process.sentinel for process in processes])
        exited = next(process for process in processes if process.sentinel in ready)
        exited.join()
        exit_code = exited.exitcode if exited.exitcode not in (None, 0) else 1
        logger.error(
            "child_exited_unexpectedly child=%r exit_code=%r",
            exited.name,
            exited.exitcode,
        )
    finally:
        for process in processes:
            if process.pid is None:
                continue
            if process.is_alive():
                process.terminate()
            process.join()
            logger.info(
                "child_exited child=%r exit_code=%r", process.name, process.exitcode
            )
    return exit_code


def main():
    configure_logging("launcher")

    from discord_bot import app
    import web

    processes = (
        multiprocessing.Process(target=app.run_bot, name="discord-bot"),
        multiprocessing.Process(target=web.start, name="registration-webhook"),
    )
    raise SystemExit(run_processes(processes))


if __name__ == "__main__":
    main()

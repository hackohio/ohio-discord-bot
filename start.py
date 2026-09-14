import logging
import multiprocessing
from multiprocessing.connection import wait

from logging_config import configure_logging

logger = logging.getLogger(__name__)


def main():
    configure_logging("launcher")

    from discord_bot import app
    import web

    processes = (
        multiprocessing.Process(target=app.run_bot, name="discord-bot"),
        multiprocessing.Process(target=web.start, name="registration-webhook"),
    )
    try:
        for process in processes:
            process.start()
            logger.info("child_started child=%r pid=%r", process.name, process.pid)
        wait([process.sentinel for process in processes])
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


if __name__ == "__main__":
    main()

from time import time

from openai import Client

from usage import print_usage


def _swap_roles(history):
    """
    Return a copy of `history` where user/assistant roles are flipped.
    System messages are left untouched so both agents share the same context.
    """
    swapped = []
    for message in history:
        role = message['role']
        if role == 'user':
            role = 'assistant'
        elif role == 'assistant':
            role = 'user'
        swapped.append({'role': role, 'content': message['content']})
    return swapped


def main():
    client = Client()
    model = "gpt-5-nano"

    history = []
    agent_a_usage = []
    agent_b_usage = []

    try:
        seed = input('Enter a starting message to Agent A (blank to quit): ').strip()
        if not seed:
            return

        # Treat Agent A as the assistant and Agent B as the user in the shared history.
        history.append({'role': 'user', 'content': seed})

        while True:
            start = time()

            # Agent A sees the original history.
            response_a = client.responses.create(
                model=model,
                input=history,
                reasoning={'effort': 'low'}
            )
            history.append({'role': 'assistant', 'content': response_a.output_text})
            agent_a_usage.append(response_a.usage)
            print('Agent A:', response_a.output_text)

            # Agent B sees the conversation with roles flipped.
            swapped_history = _swap_roles(history)
            response_b = client.responses.create(
                model=model,
                input=swapped_history,
                reasoning={'effort': 'low'}
            )
            agent_b_usage.append(response_b.usage)
            # Store Agent B's reply as a user turn so Agent A answers it next.
            history.append({'role': 'user', 'content': response_b.output_text})
            print('Agent B:', response_b.output_text)

            print(f'Round took {round(time() - start, 2)} seconds')
            cont = input("Press Enter to continue, or type 'q' to stop: ").strip().lower()
            if cont == 'q':
                break
    except KeyboardInterrupt:
        pass

    print('Agent A usage:')
    print_usage(model, agent_a_usage)
    print('Agent B usage:')
    print_usage(model, agent_b_usage)


if __name__ == '__main__':
    main()

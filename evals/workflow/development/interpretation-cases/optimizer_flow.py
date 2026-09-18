"""Source-reading case: ownership, gradient paths, and exact output values."""


def train_batch(generator, critic, generator_optimizer, critic_optimizer,
                real, noise, loss_fn, logger):
    fake = generator(noise)

    critic_optimizer.zero_grad()
    critic_loss = loss_fn(critic(real), critic(fake.detach()))
    critic_loss.backward()
    critic_optimizer.step()

    generator_optimizer.zero_grad()
    generator_loss = loss_fn(critic(fake), "real")
    generator_loss.backward()
    generator_optimizer.step()

    running_generator_loss = generator_loss.item() * len(real)
    logger.log({"generator_loss": generator_loss.item(),
                "critic_loss": critic_loss.item()})
    return fake.detach(), running_generator_loss

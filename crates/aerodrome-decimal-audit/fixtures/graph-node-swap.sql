    create table "sgd0"."swap" (
        vid                  bigserial primary key,
        block_range          int4range not null,
        "id"                 text not null,
        "transaction"        text not null,
        "timestamp"          numeric not null,
        "pool"               text not null,
        "token_0"            text not null,
        "token_1"            text not null,
        "sender"             bytea not null,
        "recipient"          bytea not null,
        "origin"             bytea not null,
        "amount_0"           numeric not null,
        "amount_1"           numeric not null,
        "amount_usd"         numeric not null,
        "sqrt_price_x96"     numeric not null,
        "tick"               numeric not null,
        "log_index"          numeric
    );

import redis

_redis_pool = redis.ConnectionPool(host='localhost', port=6379, db=0)

_CONFIG_WHITELIST_DOMAINS = "domain_white_list"


def add_whitelist_domain(domain):
    r = redis.Redis(connection_pool=_redis_pool)
    r.hset(_CONFIG_WHITELIST_DOMAINS, domain, 1)
    return bool(r.hget(_CONFIG_WHITELIST_DOMAINS, domain))


def del_whitelist_domain(domain):
    r = redis.Redis(connection_pool=_redis_pool)
    return bool(r.hdel(_CONFIG_WHITELIST_DOMAINS, domain))


def is_host_listed(host):
    try:
        r = redis.Redis(connection_pool=_redis_pool)
        valid_domain = r.hexists(_CONFIG_WHITELIST_DOMAINS, host)
        return valid_domain
    except Exception as err:
        raise err

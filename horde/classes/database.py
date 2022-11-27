from datetime import datetime, timedelta
import time
from horde.flask import db
from horde.logger import logger
from horde.vars import thing_name,thing_divisor

ALLOW_ANONYMOUS = True


def initiate_save(seconds = 1):
    logger.success(f"Initiating save in {seconds} seconds")
    # TODO - we don't want waits if we can avoid it (as this is a server)
    time.wait(seconds)
    db.session.commit()

def get_anon():
    return find_user_by_api_key('anon')

#TODO: Switch this to take this node out of operation instead?
# Or maybe just delete this
def shutdown(seconds):
    if seconds > 0:
        logger.critical(f"Initiating shutdown in {seconds} seconds")
        time.sleep(seconds)
    logger.critical(f"DB written to disk. You can now SIGTERM.")

def get_top_contributor():
    top_contribution = 0
    top_contributor = None
    #TODO Exclude anon
    top_contributor = db.session.query(User).order_by(
        User.contributed_thing.desc()
    ).first()
    return top_contributor

def get_top_worker():
    top_worker = None
    top_worker_contribution = 0
    top_worker = db.session.query(Worker).order_by(
        Worker.contributions.desc()
    ).first()
    return top_worker

def get_active_workers():
    active_workers = db.session.query(Worker).filter(
        datetime.utcnow() - Worker.last_check_in <= timedelta(seconds=300)
    ).all()
    return active_workers

def count_active_workers():
    count = 0
    active_workers = db.session.query(Worker).filter(
        datetime.utcnow() - Worker.last_check_in <= timedelta(seconds=300)
    ).all()
    for worker in active_workers:
        count += worker.threads
    return count

def compile_workers_by_ip():
    workers_per_ip = {}
    for worker in db.session.query(Worker).all():
        if worker.ipaddr not in workers_per_ip:
            workers_per_ip[worker.ipaddr] = []
        workers_per_ip[worker.ipaddr].append(worker)
    return(workers_per_ip)

def count_workers_in_ipaddr(ipaddr):
    workers_per_ip = compile_workers_by_ip()
    found_workers = workers_per_ip.get(ipaddr,[])
    return(len(found_workers))

def get_total_usage():
    totals = {
        thing_name: 0,
        "fulfilments": 0,
    }
    for worker in db.session.query(Worker).all():
        totals[thing_name] += worker.contributions
        totals["fulfilments"] += worker.fulfilments
    return(totals)

def find_user_by_oauth_id(oauth_id):
    if oauth_id == 'anon' and not ALLOW_ANONYMOUS:
        return(None)
    user = db.session.query(User).filter_by(oauth_id=oauth_id).first()
    return(user)

def find_user_by_username(username):
    ulist = username.split('#')
    if int(ulist[-1]) == 0 and not ALLOW_ANONYMOUS:
        return(None)
    # This approach handles someone cheekily putting # in their username
    user = db.session.query(User).filter_by(id=int(ulist[-1])).first()
    return(user)

def find_user_by_id(user_id):
    if int(user_id) == 0 and not ALLOW_ANONYMOUS:
        return(None)
    user = db.session.query(User).filter_by(id=user_id).first()
    return(user)

def find_user_by_api_key(api_key):
    if api_key == 0000000000 and not ALLOW_ANONYMOUS:
        return(None)
    user = db.session.query(User).filter_by(api_key=api_key).first()
    return(user)

def find_worker_by_name(worker_name):
    worker = db.session.query(Worker).filter_by(name=worker_name).first()
    return(worker)

def find_worker_by_id(worker_id):
    worker = db.session.query(Worker).filter_by(id=worker_id).first()
    return(worker)

def find_team_by_id(team_id):
    team = db.session.query(Team).filter_by(id=team_id).first()
    return(team)

def find_team_by_name(team_name):
    team = db.session.query(Team).filter(func.lower(Team.name) == func.lower(team_name)).first()
    return(team)

def get_available_models(waiting_prompts, lite_dict=False):
    models_dict = {}
    for worker in get_active_workers():
        model_name = None
        for model_name in worker.get_model_names():
            if not model_name: continue
            mode_dict_template = {
                "name": model_name,
                "count": 0,
                "workers": [],
                "performance": stats.get_model_avg(model_name),
                "queued": 0,
                "eta": 0,
            }
            models_dict[model_name] = models_dict.get(model_name, mode_dict_template)
            models_dict[model_name]["count"] += worker.threads
            models_dict[model_name]["workers"].append(worker)
    if lite_dict:
        return(models_dict)
    things_per_model = count_things_per_model()
    # If we request a lite_dict, we only want worker count per model and a dict format
    for model_name in things_per_model:
        # This shouldn't happen, but I'm checking anyway
        if model_name not in models_dict:
            # logger.debug(f"Tried to match non-existent wp model {model_name} to worker models. Skipping.")
            continue
        models_dict[model_name]['queued'] = things_per_model[model_name]
        total_performance_on_model = models_dict[model_name]['count'] * models_dict[model_name]['performance']
        # We don't want a division by zero when there's no workers for this model.
        if total_performance_on_model > 0:
            models_dict[model_name]['eta'] = int(things_per_model[model_name] / total_performance_on_model)
        else:
            models_dict[model_name]['eta'] = -1
    return(list(models_dict.values()))

def transfer_kudos(source_user, dest_user, amount):
    if source_user.is_suspicious():
        return([0,'Something went wrong when sending kudos. Please contact the mods.'])
    if dest_user.is_suspicious():
        return([0,'Something went wrong when receiving kudos. Please contact the mods.'])
    if amount < 0:
        return([0,'Nice try...'])
    if amount > source_user.kudos - source_user.min_kudos:
        return([0,'Not enough kudos.'])
    source_user.modify_kudos(-amount, 'gifted')
    dest_user.modify_kudos(amount, 'received')
    return([amount,'OK'])

def transfer_kudos_to_username(source_user, dest_username, amount):
    dest_user = find_user_by_username(dest_username)
    if not dest_user:
        return([0,'Invalid target username.'])
    if dest_user == get_anon():
        return([0,'Tried to burn kudos via sending to Anonymous. Assuming PEBKAC and aborting.'])
    if dest_user == source_user:
        return([0,'Cannot send kudos to yourself, ya monkey!'])
    kudos = transfer_kudos(source_user,dest_user, amount)
    return(kudos)

def transfer_kudos_from_apikey_to_username(source_api_key, dest_username, amount):
    source_user = find_user_by_api_key(source_api_key)
    if not source_user:
        return([0,'Invalid API Key.'])
    if source_user == get_anon():
        return([0,'You cannot transfer Kudos from Anonymous, smart-ass.'])
    kudos = transfer_kudos_to_username(source_user, dest_username, amount)
    return(kudos)

# Should be overriden
def convert_things_to_kudos(things, **kwargs):
    # The baseline for a standard generation of 512x512, 50 steps is 10 kudos
    kudos = round(things,2)
    return(kudos)

def count_waiting_requests(user, models = []):
    count = 0
    for wp in db.session.query(WaitingPromptExtended).all():
        if wp.user == user and not wp.is_completed():
            # If we pass a list of models, we want to count only the WP for these particular models.
            if len(models) > 0:
                matching_model = False
                for model in models:
                    if model in wp.get_model_names():
                        matching_model = True
                        break
                if not matching_model:
                    continue
            count += wp.n
    return(count)

def count_totals():
    queued_thing = f"queued_{thing_name}"
    ret_dict = {
        "queued_requests": 0,
        queued_thing: 0,
    }
    for wp in db.session.query(WaitingPromptExtended).all():
        current_wp_queue = wp.n + wp.count_processing_gens()["processing"]
        ret_dict["queued_requests"] += current_wp_queue
        if current_wp_queue > 0:
            ret_dict[queued_thing] += wp.things * current_wp_queue / thing_divisor
    # We round the end result to avoid to many decimals
    ret_dict[queued_thing] = round(ret_dict[queued_thing],2)
    return(ret_dict)


def get_organized_wps_by_model():
    org = {}
    #TODO: Offload the sorting to the DB through join() + SELECT statements
    all_wps = db.session.query(WaitingPromptExtended).all()
    for wp in all_wps:
        # Each wp we have will be placed on the list for each of it allowed models (in case it's selected multiple)
        # This will inflate the overall expected times, but it shouldn't be by much.
        # I don't see a way to do this calculation more accurately though
        for model in wp.get_model_names():
            if model not in org:
                org[model] = []
            org[model].append(wp)
    return(org)    

def count_things_per_model(self):
    things_per_model = {}
    org = get_organized_wps_by_model()
    for model in org:
        for wp in org[model]:
            current_wp_queue = wp.n + wp.count_processing_gens()["processing"]
            if current_wp_queue > 0:
                things_per_model[model] = things_per_model.get(model,0) + wp.things
        things_per_model[model] = round(things_per_model.get(model,0),2)
    return(things_per_model)

def get_waiting_wp_by_kudos(self):
    #TODO: Perform the sort via SQL during select
    wplist = db.session.query(WaitingPromptExtended).all()
    sorted_wp_list = sorted(wplist, key=lambda x: x.get_priority(), reverse=True)
    final_wp_list = []
    for wp in sorted_wp_list:
        if wp.needs_gen():
            final_wp_list.append(wp)
    # logger.debug([(wp,wp.get_priority()) for wp in final_wp_list])
    return(final_wp_list)

# Returns the queue position of the provided WP based on kudos
# Also returns the amount of things until the wp is generated
# Also returns the amount of different gens queued
def get_wp_queue_stats(self, wp):
    things_ahead_in_queue = 0
    n_ahead_in_queue = 0
    priority_sorted_list = get_waiting_wp_by_kudos()
    for iter in range(len(priority_sorted_list)):
        things_ahead_in_queue += priority_sorted_list[iter].get_queued_things()
        n_ahead_in_queue += priority_sorted_list[iter].n
        if priority_sorted_list[iter] == wp:
            things_ahead_in_queue = round(things_ahead_in_queue,2)
            return(iter, things_ahead_in_queue, n_ahead_in_queue)
    # -1 means the WP is done and not in the queue
    return(-1,0,0)

def get_organized_procgens_by_model():
    org = {}
    for procgen in db.session.query(ProcessingGenerationExtended).all():
        if procgen.model not in org:
            org[model] = []
        org[model].append(procgen)
    return(org)

def get_wp_by_id(self, uuid):
    return db.session.query(WaitingPromptExtended).filter_by(id=uuid).first()

def get_progen_by_id(self, uuid):
    return db.session.query(ProcessingGenerationExtended).filter_by(id=uuid).first()

def get_all_wps(self, uuid):
    return db.session.query(WaitingPromptExtended).all()

def get_progens(self, uuid):
    return db.session.query(ProcessingGenerationExtended).all()
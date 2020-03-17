/*! Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
       SPDX-License-Identifier: Apache-2.0 */

define(["app/server", "app/connections", "app/settings"],
    function(server, connections, settings) {

        var listeners = [];

        // cache events in 'set' state
        // several modules use this at the same time

        var current_set_events = [];
        var current_idle_events = [];
        var current_running_events = [];
        var previous_set_events = [];
        var previous_idle_events = [];
        var previous_running_events = [];

        // interval in millis to update the cache

        var update_interval;

        var intervalID;

        var settings_key = "app-event-update-interval";

        var retrieve_for_running_status = function(state) {
            var current_connection = connections.get_current();
            var url = current_connection[0];
            var api_key = current_connection[1];
            var current_endpoint = `${url}/channels/state/${state}`;

            return new Promise(function(resolve, reject) {
                server.get(current_endpoint, api_key)
                    .then(resolve)
                    .catch(function(error) {
                        console.log(error);
                        reject(error);
                    });
            });
        };
        
        var retrieve_for_state = function(state) {
            var current_connection = connections.get_current();
            var url = current_connection[0];
            var api_key = current_connection[1];
            var current_endpoint = `${url}/cloudwatch/events/state/${state}/groups`;

            return new Promise(function(resolve, reject) {
                server.get(current_endpoint, api_key)
                    .then(resolve)
                    .catch(function(error) {
                        console.log(error);
                        reject(error);
                    });
            });
        };

        var cache_update = function() {
            Promise.all([
                retrieve_for_state("set"), 
                retrieve_for_running_status("idle"),
                retrieve_for_running_status("running")
            ])
                .then(function([setStatus, idleStatus, runningStatus]) {
                    var idles = idleStatus.map(idle => {
                        idle.data = JSON.parse(idle.data);
                        return idle;
                    });

                    var running = runningStatus.map(run => {
                        run.data = JSON.parse(run.data);
                        return run;
                    });

                    var sets = setStatus.idle
                        .concat(setStatus.degraded)
                        .concat(setStatus.down)
                        .concat(setStatus.running);

                    console.log("updated set event cache");
                    console.log(sets);
                    console.log("updated idle status cache");
                    console.log(idles);
                    console.log("updated running status cache");
                    console.log(running);

                    if (idles.length) {
                        for (let j = 0; j < idles.length; j++) {
                            const idle = idles[j];
    
                            for (let x = 0; x < sets.length; x++) {
                                const set = sets[x];
    
                                if (set.resource_arn === idle.arn) {
                                    set.detail.idle_state = idle.data.idle_state;
                                }
                            }
                        }
                    }

                    if (running.length) {
                        for (let l = 0; l < running.length; l++) {
                            const run = running[l];
    
                            for (let y = 0; y < sets.length; y++) {
                                const set = sets[y];
    
                                if (set.resource_arn === run.arn) {
                                    set.detail.idle_state = run.data.idle_state;
                                }
                            }
                        }
                    }

                    previous_running_events = current_running_events;
                    previous_idle_events = current_idle_events;
                    previous_set_events = current_set_events;
                    current_set_events = sets;
                    current_idle_events = idles;
                    current_running_events = running;

                    var added = _.differenceBy(current_set_events, previous_set_events, "alarm_id");
                    var removed = _.differenceBy(previous_set_events, current_set_events, "alarm_id");

                    if (!added.length && !removed.length) {
                        added = _.differenceBy(current_set_events, previous_set_events, "detail.idle_state");
                        removed = _.differenceBy(previous_set_events, current_set_events, "detail.idle_state");
                    }

                    if (!added.length && !removed.length) {
                        added = _.differenceBy(current_set_events, previous_set_events, "detail.degraded");
                        removed = _.differenceBy(previous_set_events, current_set_events, "detail.degraded");
                    }

                    if (added.length || removed.length) {
                        for (let f of listeners) {
                            f(current_set_events, previous_set_events);
                        }
                    }
                }).catch(function(error) {
                    console.log(error);
                });
        };

        var load_update_interval = function() {
            return new Promise(function(resolve, reject) {
                settings.get(settings_key).then(function(value) {
                    seconds = Number.parseInt(value);
                    update_interval = seconds * 1000;
                    resolve();
                });
            });
        };

        var set_update_interval = function(seconds) {
            // create a default
            update_interval = seconds * 1000;
            return settings.put(settings_key, seconds);
        };

        var schedule_interval = function() {
            if (intervalID) {
                clearInterval(intervalID);
            }
            intervalID = setInterval(cache_update, update_interval);
            console.log("events: interval scheduled " + update_interval + "ms");
        };

        // load_update_interval().then(function() {
        //     schedule_interval();
        // });

        load_update_interval();

        return {
            "get_cached_events": function() {
                return {
                    "current": current_set_events,
                    "previous": previous_set_events
                };
            },
            "add_callback": function(f) {
                if (!listeners.includes(f)) {
                    listeners.push(f);
                }
                if (!intervalID) {
                    schedule_interval();
                }
            },
            "set_update_interval": function(seconds) {
                set_update_interval(seconds).then(function() {
                    schedule_interval();
                });
            },
            "get_update_interval": function() {
                return update_interval;
            }
        };

    });
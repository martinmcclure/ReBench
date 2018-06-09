# Copyright (c) 2009-2014 Stefan Marr <http://www.stefan-marr.de/>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
from __future__ import with_statement, print_function

from datetime import datetime
from time import time
from math import floor
import logging
import json
import re

try:
    from http.client import HTTPException
    from urllib.request import urlopen
    from urllib.parse import urlencode
except ImportError:
    from httplib import HTTPException
    from urllib import urlencode # pylint: disable=ungrouped-imports
    from urllib2 import urlopen

from .statistics import StatisticProperties


class Reporter(object):

    def __init__(self):
        self._job_completion_reported = False

    def run_failed(self, _run_id, _cmdline, _return_code, _output):
        pass

    def run_completed(self, run_id, statistics, cmdline):
        pass

    def job_completed(self, run_ids):
        if not self._job_completion_reported:
            self.report_job_completed(run_ids)
            self._job_completion_reported = True

    def set_total_number_of_runs(self, num_runs):
        pass

    def start_run(self, run_id):
        pass


class TextReporter(Reporter):

    def _configuration_details(self, run_id, statistics = None):
        result = ["\t".join(run_id.as_str_list()), " = "]
        self._output_stats(result, run_id, statistics)
        return result

    def _output_stats(self, output_list, run_id, statistics):
        if not statistics:
            return

        for field, value in statistics.__dict__.iteritems():
            if not field.startswith('_'):
                output_list.append("%s: %s " % (field, value))

    @staticmethod
    def _path_to_string(path):
        out = [path[0].as_simple_string()]
        for item in path[1:]:
            if item:
                out.append(str(item))
        return " ".join(out) + " "

    def _generate_all_output(self, run_ids):
        rows = []
        col_width = None

        for run_id in run_ids:
            stats = StatisticProperties(run_id.get_total_values())
            out = run_id.as_str_list()
            self._output_stats(out, run_id, stats)
            if col_width is None:
                col_width = [0] * len(out)
            rows.append(out)
            col_width = [max(len(col_content), col)
                         for col_content, col in zip(out, col_width)]

        for row in rows:
            result = "  ".join([col.ljust(width)
                                for col, width in zip(row, col_width)])
            yield result


class CliReporter(TextReporter):
    """ Reports to standard out using the logging framework """

    def __init__(self, executes_verbose):
        super(CliReporter, self).__init__()
        self._num_runs       = None
        self._runs_completed = 0
        self._startTime      = None
        self._runs_remaining = 0
        self._executes_verbose = executes_verbose

        # TODO: re-add support, think, we need that based on the proper config, i.e., the run id
#         self._min_runtime = configurator.statistics.min_runtime

    def run_failed(self, run_id, cmdline, return_code, output):
        # Additional information in debug mode
        result = "[%s] Run failed: %s\n" % (
            datetime.now(),
            " ".join(self._configuration_details(run_id)))
        logging.debug(result)

        # Standard error output
        if return_code == -9:
            log_msg = "Run timed out. return_code: %s"
        else:
            log_msg = "Run failed return_code: %s"

        print(log_msg % return_code)

        print("Cmd: %s\n" % cmdline)

        if run_id.bench_cfg.suite.has_max_runtime():
            logging.debug("max_runtime: %s" % run_id.bench_cfg.suite.max_runtime)
        logging.debug("cwd: %s" % run_id.bench_cfg.suite.location)

        if not self._executes_verbose and output and output.strip():
            print("Output:\n%s\n" % output)

    def run_completed(self, run_id, statistics, cmdline):
        result = "[%s] Run completed: %s\n" % (
            datetime.now(),
            " ".join(self._configuration_details(run_id, statistics)))

        logging.debug(result)

        self._runs_completed += 1
        self._runs_remaining -= 1

        if run_id.run_config.min_runtime:
            if statistics.mean < run_id.run_config.min_runtime:
                print(("WARNING: measured mean is lower than min_runtime (%s) "
                      "\t mean: %.1f\trun id: %s")
                      % (run_id.run_config.min_runtime,
                         statistics.mean,
                         run_id.as_simple_string()))
                print("Cmd: %s" % cmdline)

    def report_job_completed(self, run_ids):
        print("[%s] Job completed" % datetime.now())
        for line in self._generate_all_output(run_ids):
            print(line)

    def set_total_number_of_runs(self, num_runs):
        self._num_runs = num_runs
        self._runs_remaining = num_runs

    def start_run(self, run_id):
        if self._runs_completed > 0:
            current = time()
            data_points_per_run = run_id.run_config.number_of_data_points
            data_points_completed = (self._runs_completed *
                    data_points_per_run + len(run_id.get_data_points()))
            data_points_remaining = (self._runs_remaining *
                    data_points_per_run - len(run_id.get_data_points()))
            time_per_data_point = ((current - self._startTime) /
                data_points_completed)
            etl = time_per_data_point * data_points_remaining
            sec = etl % 60
            m   = (etl - sec) / 60 % 60
            h   = (etl - sec - m) / 60 / 60
            print(("Run %s \t runs left: %00d \t " +
                   "time left: %02d:%02d:%02d") % (run_id.bench_cfg.name,
                                                   self._runs_remaining,
                                                   floor(h), floor(m),
                                                   floor(sec)))
        else:
            self._startTime = time()
            print("Run %s \t runs left: %d" % (run_id.bench_cfg.name,
                                               self._runs_remaining))

    def _output_stats(self, output_list, run_id, statistics):
        if not statistics:
            return

        if run_id.run_failed():
            output_list.append("run failed.")
            output_list.append("")
            output_list.append("")
            output_list.append("")
        else:
            output_list.append("mean:")
            output_list.append(("%.1f" % statistics.mean).rjust(8))


class FileReporter(TextReporter):
    """ should be mainly a log file
        data is the responsibility of the data_aggregator
    """

    def __init__(self, filename):
        super(FileReporter, self).__init__()
        self._file = open(filename, 'a+')

    def run_failed(self, run_id, _cmdline, _return_code, _output):
        result = "[%s] Run failed: %s\n" % (
            datetime.now(),
            " ".join(self._configuration_details(run_id)))
        self._file.writelines(result)

    def run_completed(self, run_id, statistics, cmdline):
        result = "[%s] Run completed: %s\n" % (
            datetime.now(),
            " ".join(self._configuration_details(run_id, statistics)))
        self._file.writelines(result)

    def report_job_completed(self, run_ids):
        self._file.write("[%s] Job completed\n" % datetime.now())
        for line in self._generate_all_output(run_ids):
            self._file.write(line + "\n")

        self._file.close()


class CodespeedReporter(Reporter):
    """
    This report will report the recorded data on the completion of the job
    to the configured Codespeed instance.
    """

    def __init__(self, cfg):
        super(CodespeedReporter, self).__init__()
        self._cfg = cfg
        self._incremental_report = self._cfg.report_incrementally
        self._cache_for_seconds = 30
        self._cache = {}
        self._last_send = time()

    def run_completed(self, run_id, statistics, cmdline):
        if not self._incremental_report:
            return

        # ok, talk to codespeed immediately
        self._cache[run_id] = self._format_for_codespeed(run_id, statistics)

        if time() - self._last_send >= self._cache_for_seconds:
            self._send_and_empty_cache()

    def _send_and_empty_cache(self):
        self._send_to_codespeed(list(self._cache.values()))
        self._cache = {}

    def _result_data_template(self):
        # all None values have to be filled in
        return {
            'commitid':     self._cfg.commit_id,
            'project':      self._cfg.project,
            #'revision_date': '', # Optional. Default is taken either
                                  # from VCS integration or from current date
            'executable':   None,
            'benchmark':    None,
            'environment':  self._cfg.environment,
            'branch':       self._cfg.branch,
            'result_value': None,
            # 'result_date': datetime.today(), # Optional
            'std_dev':      None,
            'max':          None,
            'min':          None}

    @staticmethod
    def _beautify_benchmark_name(name):
        """
        Currently just remove all bench, or benchmark strings.
        """
        replace = re.compile('bench(mark)?', re.IGNORECASE)
        return replace.sub('', name)

    def _format_for_codespeed(self, run_id, stats = None):
        result = self._result_data_template()

        if stats and not run_id.run_failed():
            result['min']          = stats.min
            result['max']          = stats.max
            result['std_dev']      = stats.std_dev
            result['result_value'] = stats.mean
        else:
            result['result_value'] = -1

        result['executable'] = self._cfg.executable or run_id.bench_cfg.vm.name

        if run_id.bench_cfg.codespeed_name:
            name = run_id.bench_cfg.codespeed_name
        else:
            name = (self._beautify_benchmark_name(run_id.bench_cfg.name)
                    + " (%(cores)s cores, %(input_sizes)s %(extra_args)s)")

        # TODO: this is incomplete:
        name = name % {'cores'       : run_id.cores_as_str,
                       'input_sizes' : run_id.input_size_as_str,
                       'extra_args'  : run_id.bench_cfg.extra_args}

        result['benchmark'] = name

        return result

    def _send_payload(self, payload):
        fh = urlopen(self._cfg.url, payload)
        response = fh.read()
        fh.close()
        logging.info("Results were sent to Codespeed, response was: "
                     + response)

    def _send_to_codespeed(self, results):
        payload = urlencode({'json': json.dumps(results)})

        try:
            self._send_payload(payload)
        except (IOError, HTTPException):
            # sometimes Codespeed fails to accept a request because something
            # is not yet properly initialized, let's try again for those cases
            try:
                self._send_payload(payload)
            except (IOError, HTTPException) as error:
                logging.error(str(error) + " This is most likely caused by "
                              "either a wrong URL in the config file, or an "
                              "environment not configured in Codespeed. URL: "
                              + self._cfg.url)
                envs        = list(set([i['environment'] for i in results]))
                projects    = list(set([i['project']     for i in results]))
                benchmarks  = list(set([i['benchmark']   for i in results]))
                executables = list(set([i['executable']  for i in results]))
                logging.error("Sent data included environments: %s "
                              "projects: %s benchmarks: %s executables: %s"
                              % (envs, projects, benchmarks, executables))

        logging.info("Sent %d results to Codespeed." % len(results))

    def _prepare_result(self, run_id):
        stats = StatisticProperties(run_id.get_total_values())
        return self._format_for_codespeed(run_id, stats)

    def report_job_completed(self, run_ids):
        if self._incremental_report:
            # send remaining items from cache
            self._send_and_empty_cache()
            return

        results = [self._prepare_result(run_id) for run_id in run_ids]

        # now, send them of to codespeed
        self._send_to_codespeed(results)

<?php

namespace App\SupportedApps\CashPilot;

class CashPilot extends \App\SupportedApps implements \App\EnhancedApps
{
    public $config;

    public function test()
    {
        $test = parent::appTest($this->url('api/earnings/summary'), $this->attrs());
        echo $test->status;
    }

    public function livestats()
    {
        $status = 'inactive';
        $data = [];

        $res = parent::execute($this->url('api/earnings/summary'), $this->attrs());
        $details = json_decode($res->getBody());

        if ($details) {
            $status = 'active';

            // CashPilot distinguishes "nothing has been read yet" from "read,
            // and it is zero". has_readings is false on a fresh install and on
            // one whose collection has silently stopped -- an expired cookie,
            // deleted credentials, a wedged scheduler. Printing $0.00 in that
            // state asserts a measurement nobody took, so show a dash.
            $data['earnings'] = (isset($details->has_readings) && $details->has_readings)
                ? '$' . number_format((float) ($details->total_adjusted ?? 0), 2)
                : '—';

            // active_services is deliberately NULL when the count could not be
            // taken -- the worker query failed while containers are in fact
            // running. Rendering 0 there reads as "nothing is running", which
            // is the opposite of the truth.
            $data['running'] = isset($details->active_services) && $details->active_services !== null
                ? $details->active_services
                : '—';
        }

        return parent::getLiveStats($status, $data);
    }

    public function url($endpoint)
    {
        return parent::normaliseurl($this->config->url) . $endpoint;
    }

    public function attrs()
    {
        return [
            'headers' => [
                'Accept'        => 'application/json',
                'Authorization' => 'Bearer ' . $this->config->access_token,
            ],
        ];
    }
}

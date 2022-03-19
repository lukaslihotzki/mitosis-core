use KRdmaKit::cm::ServerCM;
use KRdmaKit::rpc::data::ReqType;

use hashbrown::HashMap;

use super::*;
use crate::conn::*;
use crate::datagram::Receiver;

use crate::future::*;

use core::marker::PhantomData;
use core::mem::transmute_copy;

/// The hook will receive datagram requests, and call the RPC callback correspondingly.
/// * Factory: the connection factory that creates the session
/// * M: the message type
/// * R: Receiver
pub struct RPCHook<'a, F, R>
where
    F: 'a + RPCFactory,
    R: Receiver,
{
    service: Service<'a>,
    session_factory: F,
    transport: R,
    connected_sessions: HashMap<usize, F::ConnType<'a>>,
}

impl<'a, F, R> RPCHook<'a, F, R>
where
    F: 'a + RPCFactory,
    R: Receiver,
{
    pub fn get_mut_service(&mut self) -> &mut Service<'a> {
        &mut self.service
    }
}

impl<'a, F, R> RPCHook<'a, F, R>
where
    F: 'a + RPCFactory,
    R: Receiver,
{
    pub fn new(factory: F, transport: R) -> Self {
        Self {
            service: Service::new(),
            session_factory: factory,
            connected_sessions: HashMap::new(),
            transport: transport,
        }
    }
}

impl<'a, F, R> Future for RPCHook<'a, F, R>
where
    F: 'a + RPCFactory,
    // we need to ensure that the polled result can be sent back to
    R: Receiver<Output = <<F as RPCFactory>::ConnType<'a> as RPCConn>::ReqPayload>,
{
    type Output = (&'a [u8], usize); // msg, session ID
    type Error = R::Error;

    fn poll(&mut self) -> Poll<Self::Output, Self::Error> {
        match self.transport.poll() {
            Ok(Async::NotReady) => Ok(Async::NotReady),
            Ok(Async::Ready(v)) => {
                unimplemented!();
            }
            Err(e) => Err(e),
        }
    }
}

use core::fmt::{Debug, Display, Formatter, Result, Write};

impl<'a, F, R> Debug for RPCHook<'a, F, R>
where
    F: 'a + RPCFactory,
    R: Receiver,
{
    fn fmt(&self, f: &mut Formatter<'_>) -> Result {
        write!(f, "RPCHook service {}", self.service)
    }
}

impl<'a, F, R> Display for RPCHook<'a, F, R>
where
    F: 'a + RPCFactory,
    R: Receiver,
{
    fn fmt(&self, f: &mut Formatter<'_>) -> Result {
        write!(f, "{:?}", self)
    }
}